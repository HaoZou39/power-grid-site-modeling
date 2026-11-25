import {siteFrameFromInfo} from "./site_frame.js";
import type {SceneFrameInfo} from "./site_frame.js";

export type SolutionContext = Readonly<{scene_id: string; frame_id: string; frame: SceneFrameInfo}>;

function geometry(frame: SceneFrameInfo): string {
  return JSON.stringify([frame.crs, frame.transform, frame.width, frame.height]);
}

export function solutionContext(sceneId: string, frame: SceneFrameInfo): SolutionContext {
  if (!sceneId) throw new Error("方案缺少所属场景。");
  siteFrameFromInfo(frame);
  const copy: SceneFrameInfo = structuredClone(frame);
  Object.freeze(copy.transform);
  Object.freeze(copy);
  return Object.freeze({scene_id: sceneId, frame_id: frame.frame_id ?? geometry(frame), frame: copy});
}

export function requireSolutionContext(context: SolutionContext | null | undefined, sceneId: string, frame?: SceneFrameInfo): SolutionContext {
  if (!context?.frame) throw new Error("方案缺少原始坐标信息，不能恢复或导出地图坐标。");
  siteFrameFromInfo(context.frame);
  if (context.scene_id !== sceneId || (frame && geometry(frame) !== geometry(context.frame))) {
    throw new Error("方案所属场景或坐标网格与当前工作区不一致。");
  }
  return context;
}

export function contextFromMetadata(sceneId: string, metadata: {
  dem?: {reference_crs?: string; target_transform?: number[]; shape?: number[]};
  data_version?: {frame_id?: string}; frame_id?: string;
  coordinate_context?: SolutionContext;
  frame?: SceneFrameInfo;
}): SolutionContext {
  if (metadata.coordinate_context) {
    const context = requireSolutionContext(metadata.coordinate_context, sceneId);
    return solutionContext(sceneId, context.frame);
  }
  if (metadata.frame) return solutionContext(sceneId, metadata.frame);
  const dem = metadata.dem;
  if (!dem?.reference_crs || dem.target_transform?.length !== 6 || dem.shape?.length !== 2) {
    throw new Error("历史结果缺少原始 CRS、transform 或网格尺寸，不能安全恢复。");
  }
  return solutionContext(sceneId, {crs: dem.reference_crs, transform: dem.target_transform as SceneFrameInfo["transform"],
    width: dem.shape[1], height: dem.shape[0], frame_id: metadata.data_version?.frame_id ?? metadata.frame_id});
}
