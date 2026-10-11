/**
 * Public satellite basemap. Swap `tiles` for an internal XYZ or tile server
 * when a deployment needs offline imagery for this region only.
 */
export const worldBasemap = {
  tiles: [
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  ],
  attribution: "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
  tileSize: 256,
};

/** Opening camera: a wide view, not the site square. */
export const initialView = {
  center: [104.5, 35.5] as [number, number],
  zoom: 3,
};

export function basemapStyle(): {
  version: 8;
  sources: {
    satellite: {
      type: "raster";
      tiles: string[];
      tileSize: number;
      attribution: string;
    };
  };
  layers: { id: string; type: "raster"; source: string }[];
} {
  return {
    version: 8,
    sources: {
      satellite: {
        type: "raster",
        tiles: worldBasemap.tiles,
        tileSize: worldBasemap.tileSize,
        attribution: worldBasemap.attribution,
      },
    },
    layers: [{ id: "satellite", type: "raster", source: "satellite" }],
  };
}
