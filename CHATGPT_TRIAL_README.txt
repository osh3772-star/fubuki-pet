# Fubuki ChatGPT Trial

GPT 구독 공식 로그인 + 짧은 텍스트 채팅 시험본입니다.

실행: START_CHATGPT_TRIAL.cmd (소스 실행), 배포 폴더의 START_CHAT.cmd (EXE 실행).
모의 실행: START_MOCK_TEST.cmd. 네트워크/계정/결제를 사용하지 않습니다.

기존 FubukiPet 및 그림은 원본 폴더에 그대로 있습니다. 시험 설정/인증은 %LOCALAPPDATA%\FubukiPetChatGPTTrial 에 분리됩니다. 자동 시작은 시험본에서 비활성화했습니다.

실제 계정 연결: Continue with ChatGPT → 앱 안내 확인 → 공식 OpenAI 브라우저에서 권한 직접 검토/승인. 로그인이 확인되면 계정의 모델 목록을 불러옵니다. API 키 입력·자동 API 과금 전환·Gemini·Claude는 없습니다. 단, 계정에 설정된 OpenAI 크레딧 정책은 앱이 변경하거나 제한하지 않습니다.

대화는 메모리에만 유지하고 새 대화/종료로 지웁니다. 기존 ChatGPT 대화/기억은 가져오지 않습니다. 키보드 감시·화면 읽기·클립보드·도구 실행은 추가하지 않았습니다.

인증: 앱 전용 OAuth PKCE, state/nonce/RS256 검증, Windows 사용자 DPAPI 보관, refresh rotation, logout revocation. 공식 endpoints만 사용합니다. 네트워크 중지 반영은 읽기 timeout에 따라 최대 약 25초 지연될 수 있습니다. 로그아웃 서버 확인이 실패하면 UI에서 알립니다.

검증: 21개 오프라인 자동 테스트 및 Windows 모의 채팅 화면 조작 통과. 실제 로그인·구독 권한·모델 응답은 사용자 승인 전이라 미검증입니다. 계정/워크스페이스 적격성에 따라 지원이 달라질 수 있습니다. 모든 DPI/다중모니터 사용감은 별도 검증이 필요합니다.

직접 source 실행 환경: Python 3.13, PySide6 Essentials, requests, PyJWT[crypto]. .venv는 이 PC 전용입니다. 복사 배포는 EXE 전체 폴더를 사용하세요.
