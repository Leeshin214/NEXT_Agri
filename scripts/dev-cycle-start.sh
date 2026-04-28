#!/bin/bash
# AgriFlow 자율 개발 사이클 시작 헬퍼.
# - macOS sleep 차단(caffeinate -i) 후 지정 시간 자동 종료
# - PM Issue 알림 받고 컴퓨터로 돌아왔을 때 한 줄로 사이클 시작
#
# Usage:
#   ./scripts/dev-cycle-start.sh         # 기본 4시간
#   ./scripts/dev-cycle-start.sh 3h      # 3시간
#   ./scripts/dev-cycle-start.sh 90m     # 90분
#   ./scripts/dev-cycle-start.sh stop    # 즉시 종료

set -e

DURATION=${1:-4h}

if [[ "$DURATION" == "stop" ]]; then
  pkill -x caffeinate 2>/dev/null && echo "✅ caffeinate 종료" || echo "ℹ️  실행 중인 caffeinate 없음"
  exit 0
fi

# DURATION → 초 변환
if [[ "$DURATION" =~ ^([0-9]+)h$ ]]; then
  SECONDS_DUR=$((${BASH_REMATCH[1]} * 3600))
elif [[ "$DURATION" =~ ^([0-9]+)m$ ]]; then
  SECONDS_DUR=$((${BASH_REMATCH[1]} * 60))
elif [[ "$DURATION" =~ ^[0-9]+$ ]]; then
  SECONDS_DUR=$DURATION
else
  echo "ERROR: DURATION 형식 오류. 사용 예: 4h, 90m, 7200" >&2
  exit 1
fi

# 기존 caffeinate 정리
pkill -x caffeinate 2>/dev/null || true

# system idle sleep 차단(-i), display sleep은 허용 → 화면 꺼져도 작업 진행
caffeinate -i -t "$SECONDS_DUR" &
CAFF_PID=$!

END_TIME=$(date -v+"${SECONDS_DUR}"S "+%H:%M:%S" 2>/dev/null || date -d "@$(($(date +%s) + SECONDS_DUR))" "+%H:%M:%S")

echo "✅ caffeinate 활성 (PID: $CAFF_PID)"
echo "   자동 종료: $END_TIME (${DURATION} 후)"
echo "   수동 종료: ./scripts/dev-cycle-start.sh stop"
echo ""
echo "다음 단계:"
echo "  1. claude code 실행"
echo "  2. \"GitHub Issue #N 의 PM Report 작업 X, Y 진행해줘.\""
echo "     \"검증 통과 후 dev에 커밋하고 caffeinate 종료해줘.\""
