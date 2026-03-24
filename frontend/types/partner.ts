export type PartnerStatus = 'ACTIVE' | 'INACTIVE' | 'PENDING';

export interface Partner {
  id: string;
  user_id: string;
  partner_user_id: string;
  nickname: string | null;
  status: PartnerStatus;
  is_favorite: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
  partner_name: string | null;
  partner_company: string | null;
  partner_role: string | null;
  partner_phone: string | null;
}

export interface PartnerCreate {
  partner_user_id: string;
  nickname?: string;
  notes?: string;
}
