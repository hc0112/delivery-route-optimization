"""규칙 모드는 AI가 아니다. API 모드는 실제 함수 호출을 이용한다."""
import re,json,requests

HELP="""지원 예시: ‘1톤 차량 2대로 설정’, ‘2톤 차량 1대로 설정’,
‘배송지 3 중형 5개 추가’, ‘배송지 3 소형 2개 취소’,
‘배송지 2 처리 지연 1.5배로 설정’, ‘실행’, ‘비교’.
차량 용량 70/140 Unit과 화물 환산계수 0.5/1/2는 시연 가정입니다.
지연 배수는 물량 처리 부분에만 적용합니다. 한 번에 한 작업을 요청하세요.
AI API 모드에서는 ‘배송이 늦어지는데 어떤 대안이 좋을까?’처럼 상황을 질문할 수도 있습니다."""

def rule_command(text):
    t=text.strip()
    if t in ['실행','최적화 실행','다시 실행']:return {'action':'run'}
    if t in ['비교','결과 비교']:return {'action':'compare'}
    if t in ['도움말','사용법']:return {'action':'help'}
    m=re.fullmatch(r'(1|2)톤 차량 (\d+)대로 설정',t)
    if m:return dict(action='fleet_set',field='small_vehicles' if m[1]=='1' else 'large_vehicles',value=int(m[2]))
    m=re.fullmatch(r'배송지 (\d+) (소형|중형|대형) (\d+)개 (추가|취소)',t)
    if m:return dict(action='demand_add',node_id=int(m[1]),size={'소형':'small','중형':'medium','대형':'large'}[m[2]],value=int(m[3])*(1 if m[4]=='추가' else -1))
    m=re.fullmatch(r'배송지 (\d+) 처리 지연 (\d+(?:\.\d+)?)배로 설정',t)
    if m:return dict(action='delay_set',node_id=int(m[1]),value=float(m[2]))
    raise ValueError('규칙 모드에서는 정해진 문장을 사용해주세요. '+HELP)

SCHEMA={"type":"object","properties":{
    "action":{"type":"string","enum":["fleet_set","demand_add","delay_set","run","compare","help"]},
    "field":{"type":"string","enum":["small_vehicles","large_vehicles"]},
    "node_id":{"type":"integer"},"size":{"type":"string","enum":["small","medium","large"]},
    "value":{"type":"number"}},"required":["action"]}

def ai_command(text,nodes,config,key,model,advisory_context=None):
    if not key or not model: raise ValueError('Gemini API 키와 함수 호출 지원 모델 ID를 입력하세요.')
    context={'nodes':[{'id':n['id'],'name':n['name']} for n in nodes], 'config':config,
             'calculated_results_and_comparison':advisory_context}
    prompt=(
      "당신은 물류 배송 경로 최적화 대시보드의 한국어 AI 조언 도우미입니다. "
      "사용자가 현재 상황을 설명하고 대안·장단점·결과 분석·추천을 물으면 도구를 호출하지 말고 한국어로 간단히 답하세요(3~5문장). "
      "배송 완료시간 단축은 makespan, 총거리 감소는 distance, 사용 차량 축소는 vehicles 목표를 고려하되, "
      "반드시 현재 조건과 계산 결과에 근거해 답하세요. 계산 결과가 없다면 예상되는 장단점만 말하고 수치나 절감 효과를 지어내지 마세요. "
      "선택한 비교 결과 A/B가 있으면 두 결과를 바탕으로 설명하되 비교 경고를 반드시 고려하세요. "
      "같은 조건에서 실행한 결과가 아니면 방법 자체의 개선 효과라고 주장하지 마세요. "
      "차량·물량·작업시간을 실제로 변경하거나 최적화 실행·단순 수치 비교를 명시적으로 요청한 경우에만 control_delivery 함수를 한 번 호출하세요. "
      "비교하면서 어느 쪽이 좋은지 물으면 수치 비교 함수 대신 설명과 추천을 글로 답하세요. "
      "fleet_set은 field=small_vehicles(1톤) 또는 large_vehicles(2톤), value=절대 대수. "
      "demand_add는 node_id,size=small/medium/large,value=증감 정수입니다. 규격 미지정 박스는 표준 박스 medium으로 취급하세요. "
      "delay_set은 node_id,value=물량 처리 지연 배수입니다. run/compare/help는 action만 사용하세요. "
      "불명확한 변경·복수 작업 요청은 한국어로 확인 질문을 하고, 미언급 조건은 변경하지 마세요. "
      "배송 경로 실제 계산은 OR-Tools가 수행합니다. 임의의 수치, 실시간 교통 상태, 시간창 충족, 비용 절감을 단정하지 마세요. "
      "현재 상태 및 검증된 데이터(JSON):"+json.dumps(context,ensure_ascii=False))
    payload={'systemInstruction':{'parts':[{'text':prompt}]},
      'contents':[{'role':'user','parts':[{'text':text}]}],
      'tools':[{'functionDeclarations':[{'name':'control_delivery','description':'배송 조건 변경 또는 실행 요청', 'parameters':SCHEMA}]}]}
    from urllib.parse import quote
    try:
        r=requests.post('https://generativelanguage.googleapis.com/v1beta/models/'+quote(model,safe='')+':generateContent',
          headers={'x-goog-api-key':key},json=payload,timeout=45)
    except requests.RequestException: raise ValueError('Gemini API 연결 실패. 네트워크를 확인하세요.')
    if not r.ok:
        # 오류 코드만 보여주면 원인(모델·요청 형식·권한)을 구분하기 어렵다.
        try:
            detail = str(r.json().get('error', {}).get('message', '')).strip()
        except (ValueError, TypeError, AttributeError):
            detail = ''
        detail = detail[:600] if detail else 'API 키·모델 접근 권한 또는 요청 형식을 확인하세요.'
        raise ValueError(f'Gemini 요청 실패 HTTP {r.status_code}: {detail}')
    candidates=r.json().get('candidates',[])
    if not candidates:raise ValueError('Gemini 응답이 비었습니다. 요청을 바꿔보세요.')
    parts=candidates[0].get('content',{}).get('parts',[])
    calls=[z['functionCall'] for z in parts if 'functionCall' in z]
    if not calls:return None,' '.join(z.get('text','') for z in parts) or '대상과 변경값을 확인해주세요.'
    if len(calls)!=1 or calls[0]['name']!='control_delivery':raise ValueError('한 번에 지원 작업 하나만 요청하세요.')
    return calls[0]['args'],None
