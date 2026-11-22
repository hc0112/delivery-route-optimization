"""배송지 관리: 기존 CVRP 모델/목적함수와 독립된 데이터 조작 로직."""
from copy import deepcopy
from core import validate_nodes

FIELDS = frozenset({'name', 'lat', 'lon', 'small', 'medium', 'large', 'fixed_min', 'per_box_min', 'delay'})


def add_destination(nodes, *, name, lat, lon, small=0, medium=0, large=0,
                    fixed_min=10, per_box_min=1, delay=1):
    """기존 ID는 변경하지 않고, 고유한 새 ID를 부여한다."""
    rows = deepcopy(nodes)
    if any(n['name'].strip() == str(name).strip() for n in rows):
        raise ValueError('같은 이름의 배송지가 이미 있습니다. 이름을 구분해 주세요.')
    next_id = max(n['id'] for n in rows) + 1
    rows.append(dict(id=next_id, name=str(name).strip(), lat=lat, lon=lon,
                     small=small, medium=medium, large=large,
                     fixed_min=fixed_min, per_box_min=per_box_min, delay=delay))
    return validate_nodes(rows)


def edit_destination(nodes, node_id, **changes):
    """센터 ID=0은 보호하고, 기존 배송지 ID는 유지한다."""
    if node_id == 0: raise ValueError('물류센터(id=0)는 배송지 관리에서 변경할 수 없습니다.')
    if not changes or set(changes) - FIELDS: raise ValueError('수정할 수 없는 배송지 항목입니다.')
    rows = deepcopy(nodes)
    target = next((n for n in rows if n['id'] == node_id), None)
    if target is None: raise ValueError('선택한 배송지가 존재하지 않습니다.')
    target.update(changes)
    if any(n['id'] != node_id and n['name'].strip() == str(target['name']).strip() for n in rows):
        raise ValueError('같은 이름의 배송지가 이미 있습니다. 이름을 구분해 주세요.')
    return validate_nodes(rows)


def delete_destination(nodes, node_id):
    if node_id == 0: raise ValueError('물류센터(id=0)는 삭제할 수 없습니다.')
    if not any(n['id'] == node_id for n in nodes): raise ValueError('선택한 배송지가 존재하지 않습니다.')
    return validate_nodes([deepcopy(n) for n in nodes if n['id'] != node_id])


def searched_coordinates(matches, index):
    """카카오 검색 결과에서 위도·경도를 추출한다(검색 호출 자체는 roads.py)."""
    if not isinstance(index,int) or index<0 or index>=len(matches):
        raise ValueError('선택한 주소 검색 결과가 없습니다.')
    row=matches[index]
    try:
        lat,lon=float(row['lat']),float(row['lon'])
    except (KeyError,TypeError,ValueError):
        raise ValueError('주소 검색 결과에 좌표가 없습니다.')
    import math
    if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat)>90 or abs(lon)>180:
        raise ValueError('주소 검색 결과의 좌표가 유효하지 않습니다.')
    return lat,lon
