"""Gemini 상황 상담에 전달할 검증 가능한 계산 사실 요약.

과거 계산 결과를 현재 설정의 결과인 것처럼 전달하지 않는다.
"""
from core import OBJECTIVES
from result_comparison import comparison_note, same_conditions, selected_pair, successful_runs


def _summary(run):
    return {
        'execution_number': run.get('run_number'),
        'goal': OBJECTIVES.get(run.get('config', {}).get('objective', 'makespan'), '목표 미상'),
        'delivery_completion_min': round(float(run['makespan_min']), 2),
        'total_distance_km': round(float(run['total_km']), 2),
        'used_vehicles': int(run['used_vehicles']),
        'vehicle_counts': {
            'one_ton': run.get('config', {}).get('small_vehicles'),
            'two_ton': run.get('config', {}).get('large_vehicles'),
        },
    }


def build_ai_context(config, nodes, runs, *, current_version, selected_ids=None):
    """전송 데이터는 선택된 실행 A/B와 현재 조건 결과만 포함한다."""
    valid = successful_runs(runs)
    current = next((r for r in reversed(valid) if r.get('version') == current_version), None)
    result = {
        'current_plan': {
            'goal': OBJECTIVES.get(config.get('objective'), '목표 미상'),
            'one_ton_available': config.get('small_vehicles'),
            'two_ton_available': config.get('large_vehicles'),
            'one_ton_capacity_unit': config.get('small_capacity'),
            'two_ton_capacity_unit': config.get('large_capacity'),
            'max_work_minutes': config.get('limit_minutes'),
            'destination_count': sum(n.get('id') != 0 for n in nodes),
            'box_count': sum(int(n.get(key, 0)) for n in nodes if n.get('id') != 0 for key in ('small', 'medium', 'large')),
        },
        'current_plan_has_calculated_result': current is not None,
        'current_result': _summary(current) if current else None,
        'saved_successful_run_count': len(valid),
        'recent_past_results_for_reference_only': [_summary(r) for r in valid[-3:]],
    }
    if selected_ids:
        selected = selected_pair(valid, *selected_ids)
        if selected:
            a, b = selected
            result['selected_comparison'] = {
                'A': _summary(a),
                'B': _summary(b),
                'same_delivery_conditions': same_conditions(a, b),
                'comparison_warning': comparison_note(a, b),
                'changes_B_minus_A': {
                    'delivery_completion_min': round(b['makespan_min']-a['makespan_min'], 2),
                    'total_distance_km': round(b['total_km']-a['total_km'], 2),
                    'used_vehicles': b['used_vehicles']-a['used_vehicles'],
                },
            }
    return result
