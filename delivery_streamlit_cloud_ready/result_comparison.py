"""선택한 두 실행 결과를 비교하는 순수 함수 (Streamlit/OR-Tools 의존 없음)."""
from core import OBJECTIVES


def successful_runs(runs):
    required = ('makespan_min', 'total_km', 'used_vehicles')
    return [r for r in runs if r.get('status') == 'feasible' and all(k in r for k in required)]


def run_label(run):
    number = run.get('run_number', '?')
    objective = run.get('config', {}).get('objective', 'makespan')
    simple_goal = {
        'makespan': '완료시간 최소화',
        'distance': '총거리 최소화',
        'vehicles': '차량 수 최소화',
    }.get(objective, OBJECTIVES.get(objective, '목표 미상'))
    return (f"실행 {number} · {simple_goal} · "
            f"{run['makespan_min']:.1f}분 / {run['total_km']:.1f}km / "
            f"{run['used_vehicles']}대")


def comparison_rows(a, b):
    """오른쪽 비교값(B)-왼쪽 비교값(A)의 차이를 표기한다."""
    return [
        {'지표': '최종 배송 완료시간',
         '결과 A': f"{a['makespan_min']:.2f}분", '결과 B': f"{b['makespan_min']:.2f}분",
         '차이 (B−A)': f"{b['makespan_min']-a['makespan_min']:+.2f}분"},
        {'지표': '총 운행거리',
         '결과 A': f"{a['total_km']:.2f}km", '결과 B': f"{b['total_km']:.2f}km",
         '차이 (B−A)': f"{b['total_km']-a['total_km']:+.2f}km"},
        {'지표': '실제 투입 차량 수',
         '결과 A': f"{a['used_vehicles']}대", '결과 B': f"{b['used_vehicles']}대",
         '차이 (B−A)': f"{b['used_vehicles']-a['used_vehicles']:+d}대"},
    ]


def same_conditions(a, b):
    """목적함수만 바꾸어 계산한 동일 환경인지 대략 확인한다.

    두 번의 실행에 행렬 서명이 있을 때는 그 값도 비교한다.
    """
    ca = {k: v for k, v in a.get('config', {}).items() if k != 'objective'}
    cb = {k: v for k, v in b.get('config', {}).items() if k != 'objective'}
    if ca != cb or a.get('nodes') != b.get('nodes') or a.get('source') != b.get('source'):
        return False
    ha, hb = a.get('matrix_signature'), b.get('matrix_signature')
    return ha == hb if ha is not None and hb is not None else True


def comparison_note(a, b):
    if not same_conditions(a, b):
        return ('두 실행의 배송지·물량·차량 설정·이동 데이터 중 일부가 다를 수 있습니다. '
                '수치 차이는 확인할 수 있지만, 이를 최적화 방식 자체의 개선 효과로 해석하면 안 됩니다.')
    if a.get('config', {}).get('objective') != b.get('config', {}).get('objective'):
        return ('동일 배송 조건에서 목적함수를 달리한 비교입니다. '
                '세 지표의 차이는 운영 목표에 따른 결과이며 알고리즘 성능 개선율을 뜻하지 않습니다.')
    return ('동일 조건·동일 목표의 두 실행 비교입니다. 탐색 시간 제한 등의 영향으로 '
            '결과가 달라질 수 있으며, 전역 최적해는 보장되지 않습니다.')


def selected_pair(runs, id_a, id_b):
    """선택한 두 실행 번호로 찾기. 다른 실행을 자동으로 대체하지 않는다."""
    by_id = {r.get('run_number'): r for r in successful_runs(runs)}
    if id_a is None or id_b is None or id_a == id_b:
        return None
    if id_a not in by_id or id_b not in by_id:
        return None
    return by_id[id_a], by_id[id_b]


def comparison_message(a, b):
    return (f"선택한 실행 {a['run_number']}과 실행 {b['run_number']} 비교 (B−A): "
            f"완료시간 {b['makespan_min']-a['makespan_min']:+.2f}분, "
            f"총거리 {b['total_km']-a['total_km']:+.2f}km, "
            f"사용 차량 {b['used_vehicles']-a['used_vehicles']:+d}대. "
            + comparison_note(a, b))


# 단위가 서로 다른 지표는 같은 축에 섞어 그리지 않는다.
CHART_METRICS = {
    '최종 배송 완료시간': ('makespan_min', '완료시간 (분)'),
    '총 운행거리': ('total_km', '운행거리 (km)'),
    '실제 투입 차량 수': ('used_vehicles', '사용 차량 (대)'),
}


def comparison_chart_rows(a, b, metric):
    """두 실행 A/B의 그래프용 수치. 비교표와 동일한 원자료를 이용한다."""
    if metric not in CHART_METRICS:
        raise ValueError('지원하지 않는 비교 그래프 지표입니다.')
    field, axis = CHART_METRICS[metric]
    return [
        {'실행': f"A · {a.get('run_number', '?')}회차", axis: float(a[field])},
        {'실행': f"B · {b.get('run_number', '?')}회차", axis: float(b[field])},
    ]
