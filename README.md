# Fubuki Pet — 공개 준비 검토 사본

현재 Windows 빌드는 단독 실행 EXE입니다. FubukiPet.exe 하나를 바탕화면이나 다른 폴더로 옮겨 실행할 수 있으며 Python 설치나 옆의 _internal 폴더가 필요하지 않습니다. 첫 실행 때 내장 파일을 임시 폴더에 푸는 데 몇 초 걸릴 수 있습니다. 이전 5MB대 폴더형 EXE는 _internal이 필요하므로 새 단독 파일과 구분하세요.

빌드는 EXE만 빈 한글·일본어 경로로 복사해 도움말과 오프라인 GUI 시작을 검사합니다. tools/build_program.py --onedir는 기존 폴더형 패키지가 필요한 경우에만 사용합니다.

후부키를 ChatGPT Work 펫 또는 독립 Windows 데스크톱 펫으로 사용하는 두 가지 패키지입니다.
현재 공개 릴리스가 아니며, 설치 파일·코드·그림의 배포 범위와 라이선스를 최종 검토해야 합니다.

| 사용 환경 | 준비된 설치 방식 | 필요한 것 |
|---|---|---|
| Windows 10/11 x64 | 설치 EXE 실행 → 설치 → 시작 메뉴에서 실행 | Python·ChatGPT 계정 불필요 |
| ChatGPT Work 웹 | 공식 공유 링크 입양, 또는 스프라이트 첨부 후 Pets로 추가 | Pets 사용 가능한 ChatGPT 계정 |

[Work 설치 안내](work-pet/INSTALL.md), [Windows 설치 프로그램 빌드](installer/README.md), [권리 검토 상태](RIGHTS_STATUS.md)를 확인하세요.
Windows 조작 방법은 [README_ko.txt](README_ko.txt)에 있습니다.

독립 Windows 펫은 로컬 마우스 상호작용·물리 동작·설정 저장을 제공합니다. 선택적으로 로컬 상태 이벤트를 받을 수 있습니다.
Windows 프로그램이 ChatGPT 웹 대화나 비공개 API를 읽지는 않습니다. Work v2의 16방향 시선은 독립 Windows 프로그램에 포함된 기능이 아닙니다.

검토 후보에는 원래 Git 이력, 개인 QA ZIP, 개인 설정, 로그, 인증 파일을 넣지 않습니다.
그림과 기존 프로그램 코드는 원본을 보존한 사본에서 준비했습니다. 설치 시험 통과와 그림·마우스·DPI·다중 모니터 사용감 검수는 별개의 결과입니다.
