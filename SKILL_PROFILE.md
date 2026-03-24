# SKILL_PROFILE.md — Profile Agent

## 역할
사용자 마이페이지 및 개인정보 관련 기능을 담당한다.
TopBar 프로필 드롭다운, 마이페이지 조회/수정, 계정 설정을 구현한다.

---

## 담당 파일

### Frontend
- `frontend/app/(dashboard)/profile/page.tsx` — 마이페이지 (조회/수정)
- `frontend/components/layout/TopBar.tsx` — 프로필 드롭다운 (마이페이지 링크 + 로그아웃)

### Backend
- `backend/app/api/v1/users.py` — `GET /api/v1/users/me`, `PATCH /api/v1/users/me`
- `backend/app/schemas/user.py` — `UserUpdateSchema`
- `backend/app/services/user_service.py` — `get_user_by_supabase_uid`, `update_user`

---

## API 스펙

### GET /api/v1/users/me
인증된 사용자의 정보 조회

**Response**
```json
{
  "data": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "홍길동",
    "role": "SELLER",
    "company_name": "AgriFlow 농장",
    "phone": "010-1234-5678",
    "profile_image": null,
    "created_at": "2026-01-01T00:00:00Z"
  }
}
```

### PATCH /api/v1/users/me
개인정보 수정 (name, company_name, phone만 허용)

**Request Body**
```json
{
  "name": "홍길동",
  "company_name": "AgriFlow 농장",
  "phone": "010-1234-5678"
}
```

**Response**: 수정된 User 객체 (`SuccessResponse<User>`)

---

## 구현 가이드

### Frontend 패턴
1. 페이지 마운트 시 `GET /users/me`를 호출해 최신 데이터를 가져오고 `setUser(res.data)`로 store 갱신
2. store 갱신 후 `useEffect([user, editing])`이 form을 자동 동기화
3. 수정 저장 후에도 `setUser(res.data)`로 전역 상태 갱신
4. 이메일은 읽기 전용 (Supabase Auth 관리 영역)

```typescript
// 마운트 시 최신 데이터 fetch — store만 의존하면 null/stale 상태로 '-' 표시됨
useEffect(() => {
  api.get<SuccessResponse<User>>('/users/me').then((res) => {
    setUser(res.data);
  }).catch(() => {
    // 네트워크 오류는 조용히 무시 — 기존 store 값으로 표시
  });
}, []); // eslint-disable-line react-hooks/exhaustive-deps
```

### form pre-fill 함정 (검증됨)

`useState` 초기값으로 `user?.name ?? ''`을 쓰면, 컴포넌트 마운트 시점에 `user`가 아직 null이면 빈 문자열로 고정된다. Zustand `persist`로 복원되거나 `useAuth`의 비동기 세션 동기화가 완료된 이후에 `user`가 채워져도 `form`은 갱신되지 않는다.

**해결: `useEffect`로 `user` 변경 시 form 동기화. 수정 중(`editing === true`)에는 덮어쓰지 않음.**

```typescript
useEffect(() => {
  if (user && !editing) {
    setForm({
      name: user.name ?? '',
      company_name: user.company_name ?? '',
      phone: user.phone ?? '',
    });
  }
}, [user, editing]);
```

이 패턴은 다음 두 문제를 동시에 해결한다:
- 조회 화면에서 값이 있어도 `-`로 표시되는 문제 → `user`가 채워지면 즉시 반영
- 수정 버튼 클릭 시 폼이 비어있는 문제 → `editing`이 `false`일 때 항상 최신 `user`로 동기화되어 있음

### Backend 패턴
```python
# JWT에서 supabase_uid 추출 후 users 테이블 조회
@router.get("/users/me", response_model=SuccessResponse[UserSchema])
async def get_me(current_user: User = Depends(get_current_user)):
    return {"data": current_user}

@router.patch("/users/me", response_model=SuccessResponse[UserSchema])
async def update_me(
    body: UserUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    updated = await user_service.update_user(db, current_user.id, body)
    return {"data": updated}
```

---

## 확장 가능 기능 (미구현)

| 기능 | 방법 |
|------|------|
| 비밀번호 변경 | `supabase.auth.updateUser({ password: newPassword })` |
| 프로필 이미지 업로드 | Supabase Storage `profile-images` 버킷 → CDN URL 저장 |
| 이메일 변경 | `supabase.auth.updateUser({ email: newEmail })` + 이메일 인증 |
| 계정 탈퇴 | Soft delete (`deleted_at` 설정) + Supabase Auth 계정 삭제 |

---

## 주의사항
- `email` 수정은 Supabase Auth를 통해야 함 — PATCH /users/me에서 제외
- RLS: `users` 테이블에서 `auth.uid() = supabase_uid` 조건 필수
- 이미지 업로드 시 파일 크기 제한 5MB, 형식: jpg/png/webp
