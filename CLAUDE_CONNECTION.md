# Claude Code 구독 연결 (시험 구현)

후부키의 공급자 선택 목록에 Claude를 추가합니다. 기존 ChatGPT, Gemini,
Antigravity Gemini 경로는 보존합니다.

## 사용 순서

1. Windows에 공식 Claude Code 네이티브 실행 파일을 설치합니다.
   https://code.claude.com/docs/en/setup
2. Claude Code의 공식 로그인 흐름에서 본인이 구독 계정으로 직접 로그인합니다.
   터미널 명령은 `claude auth login`입니다. 후부키의 CLI 로그인 버튼도 같은
   공식 명령을 별도 콘솔에서 실행합니다. 이 앱은 로그인 토큰을 받거나 읽지 않습니다.
3. 후부키 말풍선 또는 설정에서 Claude를 선택하고 로컬 Claude Code 연결을 누릅니다.
4. 연결은 `claude auth status`의 구독 직접 로그인 상태로 검증합니다.
   설치 파일 존재나 버전 확인만으로 연결 성공으로 표시하지 않습니다.
5. 사용할 모델을 선택하고 메시지를 보냅니다. 모델 및 추론강도 이용 가능 여부는
   구독과 설치된 CLI 버전에 따라 달라집니다. 실제 응답 성공 여부는 별도로 확인합니다.

## 범위와 비용

- Anthropic이 배포한 로컬 CLI를 변경 없이 실행합니다. CLI 자체를 포함하거나 배포하지 않습니다.
- API 키, 환경변수 토큰, 외부 공급자·프록시 주소를 제거하며 API 인증 상태는 거절합니다.
- 구독 사용량을 소모합니다. 계정에 이미 설정된 추가 사용 요금 정책이 적용될 수 있으므로
  Claude 계정에서 추가 사용/결제 설정을 먼저 확인하세요. 앱은 그 정책을 변경하지 않습니다.
- 별도 유료 API로 자동 전환하지 않습니다.
- 채팅 CLI는 실행 도구와 MCP, 사용자 설정·훅, 세션 저장을 비활성화합니다.
- 펫에서 연결 해제해도 공식 Claude Code 계정 자체는 로그아웃하지 않습니다.
- 응답은 완료 뒤 기존 UI 타이핑 효과로 표시합니다. 토큰 단위 실시간 스트리밍은 아닙니다.

## 검증

Cloud 환경에서 모의 단위 테스트와 Qt offscreen UI 회귀 테스트를 수행합니다.
실제 Windows 로그인, 구독 호출, Windows EXE 빌드·실행은 아직 검증하지 않았습니다.
사용자 PC를 조작하거나 실제 Claude 호출을 수행하지 않았습니다.

## 공식 근거 (2026-11-12 확인)

- https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan
- https://code.claude.com/docs/en/legal-and-compliance
- https://code.claude.com/docs/en/cli-reference

구독 로그인은 사용자가 원본 Claude Code에 직접 수행합니다. 제3자 앱이 Claude.ai
자격증명을 수집하거나 API 호출에 재사용하는 방식은 사용하지 않습니다.
