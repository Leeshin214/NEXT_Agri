CREATE TABLE ai_conversations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id),
  prompt      TEXT NOT NULL,
  response    TEXT NOT NULL,
  prompt_type TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
