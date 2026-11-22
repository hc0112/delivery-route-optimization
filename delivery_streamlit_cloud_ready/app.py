import copy, json, html, os, hashlib
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import folium
from core import DEFAULT,OBJECTIVES,demo_nodes,validate_nodes,validate_config,make_matrix,validate_matrix,solve,apply_change
from chat import HELP,rule_command,ai_command
from roads import road_matrix,road_geometry,address_search
from destination_editor import add_destination, edit_destination, delete_destination, searched_coordinates
from result_comparison import (successful_runs, run_label, comparison_rows, comparison_note,
                               selected_pair, comparison_message, CHART_METRICS, comparison_chart_rows)
from ai_context import build_ai_context
from sidebar_sync import sync_sidebar_settings

st.set_page_config(page_title='대화형 배송 계획',layout='wide')
st.title('대화형 라스트 마일 배송 계획')
st.caption('출발 전 재계획 · 단일 운행 · 분할 배송 없음 · 목표별 경로 최적화')
ss=st.session_state
if 'nodes' not in ss:
    ss.nodes=demo_nodes();ss.cfg=copy.deepcopy(DEFAULT);ss.runs=[];ss.messages=[];ss.matrix=None;ss.version=0
if 'next_run_number' not in ss:
    ss.next_run_number=max((r.get('run_number',0) for r in ss.runs),default=0)+1
st.info('기본 데이터: 제공된 nodes.xlsx의 센터 1곳·배송지 30곳·표준 박스 1,000개. 물량은 시나리오 입력값이며 좌표는 현장 출입구 검증 전입니다. 기본 계산은 OSRM 도로망을 사용합니다.')
# Streamlit 위젯 생성 전에만 키를 갱신할 수 있다.
# 챗봇 명령이 적용된 경우 다음 렌더링 시작 시 사이드바 값과 실제 계산 설정을 맞춘다.
sync_sidebar_settings(ss, ss.cfg, force=ss.pop('pending_sidebar_sync', False))

def commit_destination_change(updated_nodes, description):
    """데이터 변경 후 옛 도로 행렬·경로 기록 사용을 방지한다."""
    ss.nodes=updated_nodes
    ss.matrix=None
    ss.version+=1
    ss.destination_notice=description+' 도로 행렬은 갱신되며, 이전 실행 기록은 비교용으로 보관됩니다.'
    st.rerun()

with st.sidebar:
    st.header('1. 입력 데이터')
    up=st.file_uploader('CSV / XLSX: id=0은 센터',type=['csv','xlsx'])
    if st.button('배송지 데이터 적용',disabled=up is None):
        try:
            df=pd.read_csv(up) if up.name.endswith('.csv') else pd.read_excel(up)
            if 'demand' in df.columns and 'medium' not in df.columns:
                df=df.assign(small=0,medium=df['demand'],large=0,fixed_min=df['id'].apply(lambda v:0 if v==0 else 10),per_box_min=1.,delay=1.)
            ss.nodes=validate_nodes(df.to_dict('records'));ss.matrix=None;ss.version+=1
            st.success('데이터 적용 완료. 도로 행렬은 초기화했고 이전 실행 기록은 비교용으로 보관했습니다.')
        except Exception as e:st.error(str(e))
    st.download_button('입력 양식·예시 CSV',pd.DataFrame(demo_nodes()).to_csv(index=False).encode('utf-8-sig'),'sample_nodes.csv','text/csv')
    mu=st.file_uploader('도로 시간·거리 행렬 JSON (선택)',type=['json'])
    if st.button('행렬 적용',disabled=mu is None):
        try:
            ss.matrix=validate_matrix(json.load(mu),ss.nodes);ss.version+=1;st.success('사용자 행렬 적용 완료. 이전 실행 기록은 비교용으로 보관했습니다.')
        except Exception as e:st.error(str(e))
    st.header('주소 검색·위치 수정')
    kakao=st.text_input('카카오 REST API 키 (주소 검색용)',type='password')
    query=st.text_input('도로명주소 또는 지역+단지명')
    if st.button('주소/장소 검색'):
        try:
            ss.matches=address_search(query,kakao)
            if not ss.matches:st.warning('검색 결과 없음. 지역과 도로명주소를 구체적으로 입력하세요.')
        except Exception as e:st.error(str(e))
    if ss.get('matches'):
        pick=st.selectbox('검색 결과 확인',range(len(ss.matches)),format_func=lambda i:ss.matches[i]['label'])
        target=st.selectbox('좌표를 수정할 기존 노드', [n['id'] for n in ss.nodes],format_func=lambda i:next(n['name'] for n in ss.nodes if n['id']==i))
        if st.button('선택한 노드 좌표 교체'):
            row=ss.matches[pick]
            for n in ss.nodes:
                if n['id']==target:n['lat'],n['lon']=row['lat'],row['lon']
            ss.matrix=None;ss.version+=1;st.success('좌표 수정 완료. 재실행하면 도로 행렬도 갱신됩니다. 이전 실행 기록은 비교용으로 보관됩니다.')
    st.caption('주소 검색 결과는 기존 노드 좌표 변경뿐 아니라 오른쪽의 ‘배송지 관리’에서 신규 등록·수정할 때도 사용할 수 있습니다. 실제 출입구 위치는 지도에서 확인하세요.')
    st.header('2. 차량·계산 설정')
    with st.form('settings'):
        c=copy.deepcopy(ss.cfg)
        c['small_vehicles']=st.number_input('1톤 가용 대수',min_value=0,max_value=50,step=1,key='setting_small_vehicles')
        c['large_vehicles']=st.number_input('2톤 가용 대수',min_value=0,max_value=50,step=1,key='setting_large_vehicles')
        c['small_capacity']=st.number_input('1톤 운용 용량 (Unit)',min_value=.5,step=.5,key='setting_small_capacity')
        c['large_capacity']=st.number_input('2톤 운용 용량 (Unit)',min_value=.5,step=.5,key='setting_large_capacity')
        c['limit_minutes']=st.number_input('최대 운행시간 (분)',min_value=1.,key='setting_limit_minutes')
        st.caption('도로망 모드에서는 고정 속도 입력을 사용하지 않습니다.')
        c['search_seconds']=st.number_input('탐색 제한 (초)',min_value=1,max_value=120,step=1,key='setting_search_seconds')
        if st.form_submit_button('설정 적용'):
            try:ss.cfg=validate_config(c);ss.version+=1;st.success('적용 완료. 재실행해야 결과에 반영됩니다.')
            except Exception as e:st.error(str(e))
    mode=st.radio('대화 모드',['규칙 모드 (AI 아님·무료)','AI API 모드 (사용량 과금 가능)'])
    key=st.text_input('Gemini API 키',type='password',value=os.environ.get('GEMINI_API_KEY','')) if mode.startswith('AI') else ''
    model=st.text_input('사용 가능한 모델 ID',value=os.environ.get('GEMINI_MODEL','')) if mode.startswith('AI') else ''
    if mode.startswith('AI'):st.caption('입력 문장·배송지 이름/id·차량 설정이 API로 전송됩니다. 실제 고객 개인정보는 넣지 마세요. 키는 결과 파일에 저장하지 않습니다.')

def run_plan():
    mat=ss.matrix or road_matrix(ss.nodes)
    with st.spinner('경로 탐색 중…'):
        result=solve(ss.nodes,ss.cfg,mat)
    # 이전 기록과 비교할 수 있도록 순번과 입력 도로 행렬 서명을 보관한다.
    result['matrix_signature']=hashlib.sha256(json.dumps({
        'node_ids':mat['node_ids'],'minutes':mat['minutes'],'km':mat['km']},
        ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    result['version']=ss.version
    result['run_number']=ss.next_run_number
    ss.next_run_number+=1
    ss.runs.append(result)
    return result

def comparison():
    good=successful_runs(ss.runs)
    if len(good)<2:
        return '비교하려면 최적화를 두 번 이상 성공적으로 실행해 주세요.'
    a_id=ss.get('compare_run_a',good[0]['run_number'])
    b_id=ss.get('compare_run_b',good[-1]['run_number'])
    pair=selected_pair(good,a_id,b_id)
    if pair is None:
        return '오른쪽의 실행 결과 비교에서 서로 다른 두 결과를 선택해 주세요.'
    return comparison_message(*pair)

left,right=st.columns([1,1.3])
with left:
    st.subheader('대화로 조작하기')
    with st.expander('지원 요청과 한계',expanded=True):st.write(HELP)
    for msg in ss.messages:
        with st.chat_message(msg['role']):st.write(msg['content'])
    text=st.chat_input('예: 1톤 차량 2대로 설정')
    if text:
        ss.messages.append({'role':'user','content':text})
        with st.chat_message('user'):st.write(text)
        rerender_after_change=False
        try:
            if mode.startswith('AI'):
                context=build_ai_context(
                    ss.cfg,ss.nodes,ss.runs,current_version=ss.version,
                    selected_ids=(ss.get('compare_run_a'),ss.get('compare_run_b')))
                cmd,question=ai_command(text,ss.nodes,ss.cfg,key,model,advisory_context=context)
            else:cmd,question=rule_command(text),None
            if cmd is None:answer=question
            else:
                ns,cfg,action=apply_change(ss.nodes,ss.cfg,cmd)
                if action=='run':
                    r=run_plan();answer=r['message']
                    if r['status']=='feasible':answer+=f" 완료시간 {r['makespan_min']:.2f}분, 거리 {r['total_km']:.2f}km, 사용 차량 {r['used_vehicles']}대."
                elif action=='compare':answer=comparison()
                elif action=='help':answer=HELP
                else:
                    ss.nodes,ss.cfg=ns,cfg;ss.version+=1
                    # AI/규칙 모드의 확정값이 이전 사이드바 위젯 값에 덮이지 않도록
                    # 다음 실행의 맨 앞에서 폼 위젯 상태를 동기화한다.
                    ss.pending_sidebar_sync=True
                    rerender_after_change=True
                    answer='조건을 변경했습니다. 실행을 요청하면 계산에 반영됩니다. 적용 명령: '+json.dumps(cmd,ensure_ascii=False)
        except Exception as e:answer='처리하지 못했습니다: '+str(e)
        ss.messages.append({'role':'assistant','content':answer})
        with st.chat_message('assistant'):st.write(answer)
        if rerender_after_change:
            st.rerun()
with right:
    st.subheader('현재 조건 및 실제 계산 결과')
    st.json(ss.cfg,expanded=False)
    st.dataframe(pd.DataFrame(ss.nodes),hide_index=True)
    if ss.get('destination_notice'):
        st.success(ss.pop('destination_notice'))
    # 데이터 표를 그대로 유지하며, 필요할 때만 펼쳐 쓰는 배송지 관리 도구.
    with st.expander('배송지 관리 · 추가 / 수정 / 삭제', expanded=False):
        st.caption('주소를 좌표로 변환하려면 왼쪽의 카카오 REST API 키와 주소/장소 검색을 사용하세요. 검색 결과가 여기에 연결됩니다. 키가 없으면 위도·경도를 직접 입력할 수 있습니다.')
        tab_add,tab_edit,tab_delete=st.tabs(['배송지 추가','배송지 수정','배송지 삭제'])
        matches=ss.get('matches') or []
        def location_choice(prefix, existing=None):
            """좌표 검색 결과 선택은 form 밖에서 처리해 즉시 반영한다."""
            if matches:
                method=st.radio('위치 지정 방식', ['검색 결과 사용','좌표 직접 입력'] if prefix=='add_node' else ['좌표 직접 입력','검색 결과 사용'],horizontal=True,key=prefix+'_position_mode')
                if method=='검색 결과 사용':
                    match_index=st.selectbox('검색 결과 중 위치 선택',range(len(matches)),
                        format_func=lambda i:matches[i]['label'],key=prefix+'_match_index')
                    lat,lon=searched_coordinates(matches,match_index)
                    st.caption(f"선택한 위치: 위도 {lat:.6f}, 경도 {lon:.6f}")
                    return ('search',lat,lon)
            else:
                st.caption('검색된 주소가 없습니다. 왼쪽에서 검색하거나 좌표를 직접 입력하세요.')
            return ('manual',None,None)

        with tab_add:
            mode_add,search_lat_add,search_lon_add=location_choice('add_node')
            with st.form('add_destination_form',clear_on_submit=False):
                new_name=st.text_input('새 배송지 이름',placeholder='예: 군포 OO아파트',key='new_node_name')
                if mode_add=='manual':
                    a1,a2=st.columns(2)
                    with a1:new_lat=st.number_input('위도 (lat)',value=float(ss.nodes[0]['lat']),format='%.6f',key='add_lat')
                    with a2:new_lon=st.number_input('경도 (lon)',value=float(ss.nodes[0]['lon']),format='%.6f',key='add_lon')
                else:
                    new_lat,new_lon=search_lat_add,search_lon_add
                a1,a2,a3=st.columns(3)
                with a1:new_small=st.number_input('소형 박스',min_value=0,value=0,step=1,key='add_small')
                with a2:new_medium=st.number_input('중형 박스',min_value=0,value=0,step=1,key='add_medium')
                with a3:new_large=st.number_input('대형 박스',min_value=0,value=0,step=1,key='add_large')
                with st.expander('작업시간 설정 (기본값 사용 가능)'):
                    new_fixed=st.number_input('고정 작업시간 (분)',min_value=0.,value=10.,key='add_fixed')
                    new_per=st.number_input('박스당 작업시간 (분)',min_value=0.,value=1.,key='add_per')
                    new_delay=st.number_input('작업시간 배수',min_value=1.,value=1.,key='add_delay')
                if st.form_submit_button('배송지 추가',type='primary'):
                    try:
                        updated=add_destination(ss.nodes,name=new_name,lat=new_lat,lon=new_lon,
                            small=new_small,medium=new_medium,large=new_large,
                            fixed_min=new_fixed,per_box_min=new_per,delay=new_delay)
                        commit_destination_change(updated,f'배송지 {new_name.strip()} 추가 완료.')
                    except Exception as e:st.error(str(e))
            st.caption('물량이 모두 0이면 해당 배송지는 경로 탐색 대상에서 제외됩니다.')

        with tab_edit:
            editable=[n for n in ss.nodes if n['id']!=0]
            if editable:
                edit_id=st.selectbox('수정할 배송지', [n['id'] for n in editable],
                    format_func=lambda i:next(f"{n['id']} · {n['name']}" for n in editable if n['id']==i),
                    key='edit_destination_id')
                current=next(n for n in editable if n['id']==edit_id)
                mode_edit,search_lat_edit,search_lon_edit=location_choice('edit_node',current)
                with st.form(f'edit_destination_form_{edit_id}'):
                    edit_name=st.text_input('배송지 이름',value=current['name'])
                    if mode_edit=='manual':
                        b1,b2=st.columns(2)
                        with b1:edit_lat=st.number_input('위도 (lat)',value=float(current['lat']),format='%.6f')
                        with b2:edit_lon=st.number_input('경도 (lon)',value=float(current['lon']),format='%.6f')
                    else:
                        edit_lat,edit_lon=search_lat_edit,search_lon_edit
                    b1,b2,b3=st.columns(3)
                    with b1:edit_small=st.number_input('소형 박스',min_value=0,value=int(current['small']),step=1)
                    with b2:edit_medium=st.number_input('중형 박스',min_value=0,value=int(current['medium']),step=1)
                    with b3:edit_large=st.number_input('대형 박스',min_value=0,value=int(current['large']),step=1)
                    with st.expander('작업시간 설정 (필요한 경우 수정)'):
                        edit_fixed=st.number_input('고정 작업시간 (분)',min_value=0.,value=float(current['fixed_min']))
                        edit_per=st.number_input('박스당 작업시간 (분)',min_value=0.,value=float(current['per_box_min']))
                        edit_delay=st.number_input('작업시간 배수',min_value=1.,value=float(current['delay']))
                    if st.form_submit_button('수정 내용 저장',type='primary'):
                        try:
                            updated=edit_destination(ss.nodes,edit_id,name=edit_name,lat=edit_lat,lon=edit_lon,
                                small=edit_small,medium=edit_medium,large=edit_large,
                                fixed_min=edit_fixed,per_box_min=edit_per,delay=edit_delay)
                            commit_destination_change(updated,f'배송지 {edit_id} 수정 완료.')
                        except Exception as e:st.error(str(e))
            else:st.info('수정할 배송지가 없습니다. 배송지 추가 탭을 사용하세요.')

        with tab_delete:
            removable=[n for n in ss.nodes if n['id']!=0]
            if removable:
                delete_id=st.selectbox('삭제할 배송지', [n['id'] for n in removable],
                    format_func=lambda i:next(f"{n['id']} · {n['name']}" for n in removable if n['id']==i),
                    key='delete_destination_id')
                with st.form('delete_destination_form'):
                    confirmed=st.checkbox('선택한 배송지를 삭제하는 데 동의합니다.')
                    if st.form_submit_button('선택한 배송지 삭제'):
                        if not confirmed:st.warning('삭제 확인에 동의한 뒤 다시 눌러주세요.')
                        else:
                            try:
                                updated=delete_destination(ss.nodes,delete_id)
                                commit_destination_change(updated,f'배송지 {delete_id} 삭제 완료.')
                            except Exception as e:st.error(str(e))
            else:st.info('삭제할 배송지가 없습니다.')
        st.download_button('현재 배송지 데이터 CSV 저장',
            pd.DataFrame(ss.nodes).to_csv(index=False).encode('utf-8-sig'),
            'current_delivery_nodes.csv','text/csv',key='export_current_nodes')
        st.caption('변경 사항은 현재 브라우저 세션에서만 유지됩니다. 재사용하려면 CSV를 저장하고, 다음 실행 때 왼쪽 업로드로 불러오세요. 물류센터(id=0)는 보호됩니다.')
    # 초기 v2 UI는 그대로 유지하고, 실행 버튼 바로 위에 목적함수만 선택한다.
    selected_goal=st.radio('최적화 목표 선택',list(OBJECTIVES),
                           format_func=lambda key:OBJECTIVES[key],horizontal=True,
                           index=list(OBJECTIVES).index(ss.cfg.get('objective','makespan')),
                           key='objective_selection')
    # 선택값을 현재 계산 설정에 즉시 반영한다. 별도의 콜백 함수는 필요하지 않다.
    if selected_goal!=ss.cfg.get('objective','makespan'):
        ss.cfg['objective']=selected_goal
        ss.version+=1
    if st.button('현재 조건으로 최적화 실행',type='primary'):
        try:run_plan()
        except Exception as e:st.error(str(e))
    current_run=next((r for r in reversed(ss.runs) if r.get('version')==ss.version),None)
    if current_run is not None:
        r=current_run
        st.info(r['message']);st.caption('최적화 목표: '+r.get('objective_label',OBJECTIVES['makespan'])+' · 이동 데이터: '+r['source'])
        if r['status']=='feasible':
            c1,c2,c3=st.columns(3)
            c1.metric('완료시간 (분)',f"{r['makespan_min']:.2f}")
            c2.metric('총거리 (km)',f"{r['total_km']:.2f}")
            c3.metric('사용 차량',r['used_vehicles'])
            st.dataframe(pd.DataFrame(r['routes']),hide_index=True)
            st.caption('도로를 따라가는 경로 표시. OSRM 예상 경로이며 실시간 교통·대형차 통행 제한·출입구 정확성을 보장하지 않습니다.')
            lookup={n['id']:n for n in r['nodes']};depot=lookup[0]
            m=folium.Map([depot['lat'],depot['lon']],zoom_start=12)
            for n in r['nodes']:
                folium.Marker([n['lat'],n['lon']],tooltip=html.escape(n['name'])).add_to(m)
            colors=['blue','red','green','purple','orange','black']
            for j,route in enumerate(r['routes']):
                try:
                    line=road_geometry(route,r['nodes'])
                    folium.PolyLine(line,color=colors[j%len(colors)],tooltip=f"차량 {route['vehicle']}").add_to(m)
                except Exception as e:st.warning(f"차량 {route['vehicle']} 경로 표시 실패: {e}")
            components.html(m.get_root().render(),height=430)
    elif ss.runs:
        st.info('현재 조건으로 계산한 결과가 아직 없습니다. 이전 실행 기록은 아래에서 비교할 수 있습니다.')

    st.divider()
    st.subheader('실행 결과 비교')
    good=successful_runs(ss.runs)
    if len(good)<2:
        st.caption('최적화를 두 번 이상 성공적으로 실행하면 원하는 두 결과를 선택해 비교할 수 있습니다.')
    else:
        options=[r['run_number'] for r in good]
        labels={r['run_number']:run_label(r) for r in good}
        if ss.get('compare_run_a') not in options:
            ss.compare_run_a=options[0]
        a_id=st.selectbox('기준 결과 (A)',options,format_func=lambda num:labels[num],key='compare_run_a')
        options_b=[num for num in options if num!=a_id]
        if ss.get('compare_run_b') not in options_b:
            ss.compare_run_b=options_b[-1]
        b_id=st.selectbox('비교할 결과 (B)',options_b,format_func=lambda num:labels[num],key='compare_run_b')
        pair=selected_pair(good,a_id,b_id)
        if pair:
            a,b=pair
            st.dataframe(pd.DataFrame(comparison_rows(a,b)),hide_index=True,use_container_width=True)
            st.caption('차이 = 결과 B − 결과 A. 음수는 값이 감소했다는 뜻입니다.')
            st.caption(comparison_note(a,b))
            # 기존 비교표는 유지하고, 선택한 지표 하나만 간단한 막대그래프로 표시한다.
            chart_metric=st.selectbox('비교 그래프 지표',list(CHART_METRICS),key='comparison_chart_metric')
            chart_axis=CHART_METRICS[chart_metric][1]
            chart_df=pd.DataFrame(comparison_chart_rows(a,b,chart_metric))
            st.bar_chart(chart_df,x='실행',y=chart_axis,height=220,use_container_width=True)
    if ss.runs:
        st.download_button('전체 실행 기록 JSON',json.dumps(ss.runs,ensure_ascii=False,indent=2),
                           'runs.json','application/json')
