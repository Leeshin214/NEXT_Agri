export interface ScheduleRecommendation {
  recommended_date: string;
  product_name: string | null;
  recommended_quantity: number | null;
  unit: string | null;
  reasoning: string;
}

export interface ScheduleRecommendResponse {
  has_recommendation: boolean;
  recommendations: ScheduleRecommendation[];
  message: string;
}
