export type SiteReport = {
  footprint_slope_deg: number;
  slope_limit_deg: number;
  access_rise_m: number | null;
  access_slope_deg: number | null;
  access_warning: boolean;
  access_error?: string;
  road_haul_m: number | null;
  offroad_haul_m: number | null;
  haul_rise_m: number | null;
  haul_path: [number, number][] | null;
};
