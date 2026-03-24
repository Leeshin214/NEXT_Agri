from supabase import create_client, Client

from app.core.config import settings


def get_supabase_client() -> Client:
    """Supabase 서비스 롤 클라이언트 (RLS 무시)"""
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_ROLE_KEY,
    )
