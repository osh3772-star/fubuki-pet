# 추론 강도 지원과 검증 범위

후부키는 공통 추론 단계 이름을 모든 모델의 지원 목록으로 취급하지 않습니다.

- 기본값은 강도를 별도로 지정하지 않는다는 뜻입니다. 문자열 `none`과 다릅니다.
- ChatGPT 구독 연결: 공식 계정 모델 목록에서 단계별 지원을 확인할 수 없으므로 기본값만 제공합니다. 모델 이름이나 일반 Responses API enum으로 지원을 추측하지 않습니다.
- Claude Code: 연결 시 공식 초기화 제어 응답의 모델별 `supportsEffort`와 `supportedEffortLevels`를 확인합니다. 사용자 메시지나 추론 요청은 보내지 않습니다. 조회 실패·알 수 없는 모델·자동 모델은 기본값만 제공합니다. 명시 선택 시 자식 프로세스에서만 `CLAUDE_CODE_EFFORT_LEVEL`을 제거해 환경변수 우선순위 충돌을 막습니다. 전역 환경은 변경하지 않습니다.
- Antigravity: 별도 강도 지원을 확인할 안정적인 응답 스키마가 없어 기본값만 제공합니다. 실제 모델 목록의 high/medium/low 변형 모델 선택은 유지합니다. 구버전에서 추론이 될 수 있는 `/effort` 조회를 자동 실행하지 않습니다.
- Gemini CLI: 모델 문서의 LOW/HIGH 지원과 설치된 CLI에서 설정이 실제로 적용되는지는 별개입니다. 시스템 설정·모델 override 우선순위를 검증하지 못하므로 기본값만 제공합니다. 이전 후부키가 생성한 것으로 정확히 일치하는 강도 override만 기본값 전송 시 정리하며, 다른 사용자 설정은 보존합니다.

모델·제공자 변경 및 새로고침 때 표시 단계를 다시 검사하고, 요청 직전에도 확인되지 않은 명시적 값을 차단합니다. 지원 단계 조회는 실제 추론량이나 서버 측 정책 적용을 보장하지 않습니다. 조직 제한이나 CLI 버전은 추가 제약을 줄 수 있습니다. 오프라인 모의 요청 검사와 Windows 실행 검사는 실제 계정의 서비스 추론 시험이 아닙니다.

## 공식 근거

- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/api/docs/guides/reasoning
- https://code.claude.com/docs/en/agent-sdk/typescript#modelinfo
- https://code.claude.com/docs/en/model-config#adjust-effort-level
- https://antigravity.google/docs/cli/commands/effort/
- https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md
- https://geminicli.com/docs/cli/generation-settings/
- https://geminicli.com/docs/reference/configuration/
