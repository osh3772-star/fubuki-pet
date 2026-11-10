후부키 말풍선 시험본

START_MOCK_TEST.cmd: 계정과 네트워크 없이 모의 시험.
START_CHATGPT_TRIAL.cmd: 실제 연결용 화면.
- 공급자 선택: ChatGPT 구독(OpenAI 공식 로그인) / Gemini(로컬 Gemini CLI 로그인) / Antigravity Gemini(로컬 Antigravity CLI 로그인) 3가지를 말풍선 상단 드롭다운, 우클릭 메뉴, 설정 창에서 각각 선택할 수 있습니다.
- Claude 및 API 키 방식은 포함하지 않으며, 로컬 CLI 호출 시 API 키 환경변수(GEMINI_API_KEY 등)는 자동으로 제거됩니다.
- 캐릭터 옆 대화 버튼으로 입력/응답 말풍선을 펼칩니다. Enter 전송, Shift+Enter 줄바꿈, Esc 접기. 입력 초안은 접어도 유지됩니다. 설정 버튼은 계정/모델 창을 엽니다.
- 원본 및 이전 시험본은 변경하지 않았습니다. 별도 데이터 폴더 FubukiPetBubbleTrial 사용. 대화는 메모리만 사용합니다.
- 실행 스크립트는 이전 시험본의 Python 가상환경을 사용합니다. 두 폴더를 함께 보존하세요.
- 모니터 경계는 논리좌표로 검사합니다. 실제 다중 모니터/DPI 전환과 한글 IME 실기 검증은 별도로 필요합니다.

검증 기록: 자동 테스트 81개 통과. 로컬 Gemini CLI(v0.66.0) 및 로컬 Antigravity CLI(v1.4.7, Gemini 전용 모델 필터링) 실제 연결 및 말풍선 응답 수신 확인.
