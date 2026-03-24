CREATE TABLE calendar_events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id),
  order_id    UUID REFERENCES orders(id),
  title       TEXT NOT NULL,
  event_type  TEXT NOT NULL CHECK (event_type IN (
                'SHIPMENT', 'DELIVERY', 'MEETING', 'QUOTE_DEADLINE', 'ORDER', 'OTHER'
              )),
  event_date  DATE NOT NULL,
  start_time  TIME,
  end_time    TIME,
  description TEXT,
  is_allday   BOOLEAN DEFAULT true,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER set_updated_at BEFORE UPDATE ON calendar_events
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
