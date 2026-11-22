"""AI 명령과 사이드바 입력창 사이의 설정 상태 동기화.

Streamlit은 위젯을 생성한 뒤 해당 위젯의 session_state 키를 바꿀 수 없다.
따라서 변경 요청은 플래그로 저장하고 다음 렌더링 시작 시 동기화한다.
"""

SIDEBAR_FIELDS = (
    'small_vehicles', 'large_vehicles',
    'small_capacity', 'large_capacity',
    'limit_minutes', 'search_seconds',
)
INTEGER_FIELDS = frozenset(('small_vehicles', 'large_vehicles', 'search_seconds'))


def widget_key(field):
    if field not in SIDEBAR_FIELDS:
        raise ValueError('지원하지 않는 사이드바 설정 항목입니다.')
    return 'setting_' + field


def sync_sidebar_settings(state, config, force=False):
    """렌더링 *전* 호출. force=True면 AI가 확정한 설정값을 위젯에 반영."""
    for field in SIDEBAR_FIELDS:
        key = widget_key(field)
        if force or key not in state:
            state[key] = int(config[field]) if field in INTEGER_FIELDS else float(config[field])
