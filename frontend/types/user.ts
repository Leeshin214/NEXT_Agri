export type UserRole = 'SELLER' | 'BUYER' | 'ADMIN';

export interface User {
  id: string;
  supabase_uid: string;
  email: string;
  name: string;
  role: UserRole;
  company_name: string | null;
  phone: string | null;
  profile_image: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface UserPublicProfile {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  company_name: string | null;
  phone: string | null;
  profile_image: string | null;
  created_at: string;
}
