import type { SiteEdit, SitePose } from "./site_edit.js";

export type BuildingMeters = { widthM: number; heightM: number };

/** Size of one full search. It becomes the map size only when that job's solutions are installed. */
export type SubmittedBuildingSize = BuildingMeters & { jobId: string };

/**
 * A search request may use a new size. Solutions already on the map keep theirs
 * until that search's results replace them.
 */
export function preserveDisplayedSize<Pose extends SitePose>(
  request: SiteEdit<Pose>,
  displayed: BuildingMeters,
): SiteEdit<Pose> {
  if (request.poses.length === 0) return request;
  return request.withBuilding(displayed.widthM, displayed.heightM);
}

export function submittedBuildingSize(jobId: string, request: BuildingMeters): SubmittedBuildingSize {
  return { jobId, widthM: request.widthM, heightM: request.heightM };
}

/** Install new solutions and their size together. Another job's size is ignored. */
export function installSearchSolutions<Pose extends SitePose>(
  displayed: SiteEdit<Pose>,
  submitted: SubmittedBuildingSize | null,
  jobId: string,
  poses: readonly Pose[],
): SiteEdit<Pose> {
  const sized = submitted?.jobId === jobId
    ? displayed.withBuilding(submitted.widthM, submitted.heightM)
    : displayed;
  return sized.withPoses(poses);
}
