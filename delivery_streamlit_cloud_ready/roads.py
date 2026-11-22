"""OSRM public demo: no uptime/SLA guarantee. Kakao search requires separate key."""
import requests,json,hashlib
from pathlib import Path
CACHE=Path(__file__).parent/'road_cache'

def get_json(url,params=None,headers=None):
    try:
        r=requests.get(url,params=params,headers=headers,timeout=45);r.raise_for_status();return r.json()
    except (requests.RequestException,ValueError):raise ValueError('외부 지도 서비스 요청 실패. 인터넷·서비스 한도를 확인하고 잠시 후 재시도하세요. 직선거리로 대체하지 않았습니다.')

def road_matrix(nodes):
    points=[(n['id'],n['lat'],n['lon']) for n in nodes]
    key=hashlib.sha256(json.dumps(points).encode()).hexdigest()
    CACHE.mkdir(exist_ok=True);path=CACHE/(key+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    coords=';'.join(f"{n['lon']},{n['lat']}" for n in nodes)
    data=get_json('https://router.project-osrm.org/table/v1/driving/'+coords,{'annotations':'duration,distance'})
    if data.get('code')!='Ok' or 'durations' not in data or 'distances' not in data:raise ValueError('도로 행렬을 받지 못했습니다. OSRM 응답을 확인하세요.')
    if any(v is None for row in data['durations'] for v in row) or any(v is None for row in data['distances'] for v in row):raise ValueError('일부 구간에 도로 경로가 없습니다. 좌표와 진입 가능 도로를 확인하세요.')
    result={'node_ids':[n['id'] for n in nodes],'minutes':[[v/60 for v in row] for row in data['durations']],
      'km':[[v/1000 for v in row] for row in data['distances']], 'source':'OSRM 도로망 기반 예상 이동시간·거리 (실시간 교통 아님)',
      'coordinate_signature':points}
    path.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');return result

def road_geometry(route,nodes):
    lookup={n['id']:n for n in nodes};points=[lookup[i] for i in route['ids']]
    key=hashlib.sha256(json.dumps([(n['lat'],n['lon']) for n in points]).encode()).hexdigest()
    CACHE.mkdir(exist_ok=True);path=CACHE/('geometry_'+key+'.json')
    if path.exists():return json.loads(path.read_text())
    coords=';'.join(f"{n['lon']},{n['lat']}" for n in points)
    data=get_json('https://router.project-osrm.org/route/v1/driving/'+coords,{'overview':'full','geometries':'geojson','steps':'false','continue_straight':'false'})
    if data.get('code')!='Ok' or not data.get('routes'):raise ValueError('지도용 도로 경로를 받지 못했습니다.')
    line=[[lat,lon] for lon,lat in data['routes'][0]['geometry']['coordinates']]
    path.write_text(json.dumps(line));return line

def address_search(query,key):
    if not key:raise ValueError('카카오 REST API 키가 필요합니다. Gemini 키와 다릅니다.')
    hdr={'Authorization':'KakaoAK '+key}
    rows=get_json('https://dapi.kakao.com/v2/local/search/address.json',{'query':query},hdr).get('documents',[])
    if rows:return [dict(label=r['address_name'],lat=float(r['y']),lon=float(r['x'])) for r in rows]
    rows=get_json('https://dapi.kakao.com/v2/local/search/keyword.json',{'query':query},hdr).get('documents',[])
    return [dict(label=r['place_name']+' | '+(r.get('road_address_name') or r.get('address_name','')),lat=float(r['y']),lon=float(r['x'])) for r in rows]
