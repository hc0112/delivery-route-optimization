"""출발 전 정적 CVRP. 실제 박스 수와 환산 적재량을 분리한다."""
import copy, math, json, statistics
from decimal import Decimal

DEFAULT = {"small_vehicles": 8, "large_vehicles": 4,
           "small_capacity": 70, "large_capacity": 140,
           "speed_kmh": 25, "limit_minutes": 480, "search_seconds": 10,
           "objective": "makespan"}

OBJECTIVES = {
    'makespan': '최종 배송 완료시간 최소화 (기존 목표)',
    'distance': '총 운행거리 최소화',
    'vehicles': '투입 차량 수 최소화',
}


def demo_nodes():
    from pathlib import Path
    import csv
    with (Path(__file__).parent/'nodes_original.csv').open(encoding='utf-8-sig') as f:
        return [dict(id=int(r['id']),name=r['name'],lat=float(r['lat']),lon=float(r['lon']),
                     small=0,medium=int(r['demand']),large=0,
                     fixed_min=0 if int(r['id'])==0 else 10,per_box_min=1.,delay=1.) for r in csv.DictReader(f)]


def finite_number(v, label, minimum=0, integer=False):
    if isinstance(v,bool): raise ValueError(label+": 참/거짓 값은 허용하지 않습니다.")
    try: f=float(v)
    except (TypeError,ValueError): raise ValueError(label+": 숫자가 필요합니다.")
    if not math.isfinite(f) or f<minimum or (integer and f!=int(f)):
        raise ValueError(label+": 허용 범위를 벗어났습니다.")
    return int(f) if integer else f


def validate_nodes(rows):
    if not isinstance(rows,list) or not rows: raise ValueError("배송지 데이터가 비었습니다.")
    result=[];ids=set()
    for raw in rows:
        x=dict(raw);x['id']=finite_number(x['id'],'id',integer=True)
        if x['id'] in ids: raise ValueError("id는 중복될 수 없습니다.")
        ids.add(x['id'])
        if not isinstance(x.get('name'),str) or not x['name'].strip(): raise ValueError("배송지 이름이 필요합니다.")
        for field in ['small','medium','large']: x[field]=finite_number(x[field],field,integer=True)
        for field in ['fixed_min','per_box_min','delay']: x[field]=finite_number(x[field],field)
        if x['delay']<1: raise ValueError("delay는 1 이상이어야 합니다.")
        for field,bound in [('lat',90),('lon',180)]:
            x[field]=float(x[field])
            if not math.isfinite(x[field]) or abs(x[field])>bound: raise ValueError("좌표 범위 오류")
        result.append(x)
    if 0 not in ids: raise ValueError("id=0인 물류센터가 필요합니다.")
    result.sort(key=lambda x:x['id'])
    if sum(result[0][f] for f in ['small','medium','large']): raise ValueError("물류센터의 물량은 0이어야 합니다.")
    result[0]['fixed_min']=0
    return result


def validate_config(c):
    c=copy.deepcopy(c)
    c.setdefault('objective','makespan')
    if c['objective'] not in OBJECTIVES:
        raise ValueError('최적화 목표는 완료시간, 총거리, 차량 수 중 하나여야 합니다.')
    for f in ['small_vehicles','large_vehicles']: c[f]=finite_number(c[f],f,integer=True)
    for f in ['small_capacity','large_capacity','speed_kmh','limit_minutes']: c[f]=finite_number(c[f],f,minimum=.01)
    c['search_seconds']=finite_number(c['search_seconds'],'search_seconds',minimum=1,integer=True)
    if c['search_seconds']>120: raise ValueError("탐색시간은 최대 120초입니다.")
    if c['small_vehicles']+c['large_vehicles']>50: raise ValueError("시연 버전은 최대 50대입니다.")
    return c


def load_units(n): return .5*n['small']+n['medium']+2*n['large']
def service_minutes(n): return n['fixed_min']+n['delay']*n['per_box_min']*sum(n[f] for f in ['small','medium','large'])

def haversine(a,b):
    la1,la2=map(math.radians,[a['lat'],b['lat']]); dl=math.radians(b['lon']-a['lon']);da=la2-la1
    v=math.sin(da/2)**2+math.cos(la1)*math.cos(la2)*math.sin(dl/2)**2
    return 6371*2*math.asin(math.sqrt(min(1,max(0,v))))


def make_matrix(nodes,config):
    # 학습용 거리 근사. 실제 도로 데이터가 아님.
    d=[[haversine(a,b) for b in nodes] for a in nodes]
    return {'node_ids':[n['id'] for n in nodes], 'minutes':[[v/config['speed_kmh']*60 for v in row] for row in d],
            'km':d,'source':'직선거리·일정 속도 가정 (실제 도로 아님)'}


def validate_matrix(matrix,nodes):
    if matrix['node_ids'] != [n['id'] for n in nodes]: raise ValueError("행렬 node_ids 순서가 CSV의 id 오름차순과 다릅니다.")
    size=len(nodes)
    for key in ['minutes','km']:
        a=matrix[key]
        if len(a)!=size or any(len(row)!=size for row in a): raise ValueError("행렬 크기 오류")
        for i,row in enumerate(a):
            for j,v in enumerate(row):
                finite_number(v,key)
                if i==j and float(v)!=0: raise ValueError("행렬 대각선은 0이어야 합니다.")
    return matrix


def apply_change(nodes,config,cmd):
    # 한 요청을 복사본에 적용한 후 전체 검증. 오류가 나면 원본을 바꾸지 않는다.
    ns=copy.deepcopy(nodes);cfg=copy.deepcopy(config)
    allowed={'action','field','value','node_id','size'}
    if not isinstance(cmd,dict) or set(cmd)-allowed: raise ValueError("지원하지 않는 명령 필드입니다.")
    act=cmd.get('action')
    if act in ['run','compare','help']:
        if set(cmd)!={'action'}: raise ValueError("실행/비교 명령에는 다른 변경을 함께 넣지 마세요.")
        return ns,cfg,act
    if act=='fleet_set':
        if set(cmd)!={'action','field','value'} or cmd['field'] not in ['small_vehicles','large_vehicles']: raise ValueError("차량 설정 형식 오류")
        cfg[cmd['field']]=finite_number(cmd['value'],'차량 수',integer=True)
    elif act=='demand_add':
        if set(cmd)!={'action','node_id','size','value'} or cmd['size'] not in ['small','medium','large']: raise ValueError("물량 변경 형식 오류")
        nid=finite_number(cmd['node_id'],'node_id',minimum=1,integer=True)
        target=next((n for n in ns if n['id']==nid),None)
        if target is None: raise ValueError("해당 배송지 id가 없습니다.")
        v=cmd['value']
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or int(v)!=v: raise ValueError("증감 개수는 정수여야 합니다.")
        target[cmd['size']]+=int(v)
    elif act=='delay_set':
        if set(cmd)!={'action','node_id','value'}: raise ValueError("지연 변경 형식 오류")
        nid=finite_number(cmd['node_id'],'node_id',minimum=1,integer=True)
        target=next((n for n in ns if n['id']==nid),None)
        if target is None: raise ValueError("해당 배송지 id가 없습니다.")
        target['delay']=finite_number(cmd['value'],'지연 배수',minimum=1)
    else: raise ValueError("지원하지 않는 작업입니다. 도움말을 확인해 주세요.")
    return validate_nodes(ns),validate_config(cfg),'updated'


def solve(nodes,config,matrix):
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    nodes=validate_nodes(nodes);config=validate_config(config);validate_matrix(matrix,nodes)
    active=[0]+[i for i,n in enumerate(nodes) if n['id']!=0 and sum(n[f] for f in ['small','medium','large'])>0]
    capacities=[config['small_capacity']]*config['small_vehicles']+[config['large_capacity']]*config['large_vehicles']
    dem=[int(Decimal(str(load_units(nodes[i])))*2) for i in active]
    caps=[]
    for v in capacities:
        scaled=Decimal(str(v))*2
        if scaled!=scaled.to_integral_value(): raise ValueError("차량 용량은 0.5 Unit 단위로 입력하세요.")
        caps.append(int(scaled))
    base={'config':copy.deepcopy(config),'nodes':copy.deepcopy(nodes),
          'source':matrix.get('source','사용자 제공 행렬'),
          'objective_label':OBJECTIVES[config['objective']]}
    def fail(status,message): return dict(base,status=status,message=message,routes=[])
    if len(active)==1:return dict(base,status='feasible',message='배송 물량 없음',routes=[],makespan_min=0,total_km=0,used_vehicles=0,std_minutes=0)
    if not caps or sum(dem)>sum(caps):return fail('precheck_infeasible','총 적재 용량이 부족합니다. 차량 수·용량 또는 물량을 변경해 주세요.')
    if max(dem)>max(caps):return fail('precheck_infeasible','단일 배송지 물량을 실을 수 있는 차량이 없습니다. 분할 배송은 지원하지 않습니다.')
    def seconds(v): return int((Decimal(str(v))*60).to_integral_value(rounding='ROUND_HALF_UP'))
    svc=[0 if nodes[i]['id']==0 else seconds(service_minutes(nodes[i])) for i in active]
    tt=[[seconds(matrix['minutes'][i][j]) for j in active] for i in active]
    manager=pywrapcp.RoutingIndexManager(len(active),len(caps),0)
    routing=pywrapcp.RoutingModel(manager)
    def transit(a,b):
        i,j=manager.IndexToNode(a),manager.IndexToNode(b)
        return tt[i][j]+svc[i]
    cb=routing.RegisterTransitCallback(transit)
    routing.AddDimension(cb,0,seconds(config['limit_minutes']),True,'Time')
    td=routing.GetDimensionOrDie('Time')
    # 배송지 방문·용량·운행시간 제약은 그대로 두고, 목적함수만 전환한다.
    objective=config['objective']
    if objective=='makespan':
        # 출발 시각은 0. 마지막 차량의 복귀 완료시간을 최소화한다.
        zero=routing.RegisterTransitCallback(lambda a,b:0)
        routing.SetArcCostEvaluatorOfAllVehicles(zero)
        td.SetGlobalSpanCostCoefficient(1)
    else:
        # OR-Tools의 정수 비용 사용을 위해 km를 미터로 환산한다.
        dm=[[int((Decimal(str(matrix['km'][i][j]))*1000).to_integral_value(rounding='ROUND_HALF_UP'))
             for j in active] for i in active]
        distance_cb=routing.RegisterTransitCallback(
            lambda a,b:dm[manager.IndexToNode(a)][manager.IndexToNode(b)])
        routing.SetArcCostEvaluatorOfAllVehicles(distance_cb)
        if objective=='vehicles':
            # 사용 차량 한 대의 고정비가 가능한 전체 주행거리 비용보다 크도록 지정.
            # 따라서 1순위는 차량 수, 같은 수라면 총거리 최소화.
            max_arc=max(max(row) for row in dm)
            upper_bound=(len(active)-1+len(caps))*max_arc
            routing.SetFixedCostOfAllVehicles(upper_bound+1)
    demand_cb=routing.RegisterUnaryTransitCallback(lambda idx:dem[manager.IndexToNode(idx)])
    routing.AddDimensionWithVehicleCapacity(demand_cb,0,caps,True,'Capacity')
    # AddDisjunction을 쓰지 않는다. 모든 활성 배송지 방문은 필수다.
    par=pywrapcp.DefaultRoutingSearchParameters()
    par.first_solution_strategy=routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    par.local_search_metaheuristic=routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    par.time_limit.seconds=config['search_seconds']
    sol=routing.SolveWithParameters(par)
    if not sol:return fail('not_found','설정된 탐색 예산에서 계획을 찾지 못했습니다. 불가능이 증명된 것은 아닙니다.')
    routes=[];visited=[]
    for k,cap in enumerate(capacities):
        idx=routing.Start(k);path=[]
        while not routing.IsEnd(idx):
            path.append(active[manager.IndexToNode(idx)])
            idx=sol.Value(routing.NextVar(idx))
        path.append(0)
        if len(path)<=2:continue
        body=path[1:-1];visited.extend(body)
        travel=sum(seconds(matrix['minutes'][a][b]) for a,b in zip(path,path[1:]))/60
        service=sum(seconds(service_minutes(nodes[i])) for i in body)/60
        total=sol.Value(td.CumulVar(routing.End(k)))/60
        if abs(total-travel-service)>1e-6:raise RuntimeError('시간 집계 검증 실패')
        load=sum(load_units(nodes[i]) for i in body)
        if load>cap+1e-8:raise RuntimeError('용량 검증 실패')
        routes.append(dict(vehicle=k+1,capacity=cap,load=load,utilization_pct=load/cap*100,
                           ids=[nodes[i]['id'] for i in path],names=[nodes[i]['name'] for i in path],
                           travel_min=travel,service_min=service,total_min=total,
                           km=sum(float(matrix['km'][a][b]) for a,b in zip(path,path[1:]))))
    if sorted(visited)!=sorted(active[1:]):raise RuntimeError('방문 충족 검증 실패')
    times=[r['total_min'] for r in routes]
    return dict(base,status='feasible',message='실행 가능한 경로를 찾았습니다. 전역 최적해 보장은 없습니다.',routes=routes,
                makespan_min=max(times,default=0),total_km=sum(r['km'] for r in routes),
                used_vehicles=len(routes),std_minutes=statistics.pstdev(times) if times else 0)
