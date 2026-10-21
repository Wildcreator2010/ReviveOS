"use client";

import { DEFAULT_WALLPAPER, useWallpaper } from "./wallpaper";

export function WallpaperBackground() {
  const wallpaper = useWallpaper();
  return (
    <div className="wallpaper" aria-hidden="true">
      <div className="wallpaper-image" style={{ backgroundImage: `url("${wallpaper || DEFAULT_WALLPAPER}")` }} />
      <div className="wallpaper-mask" />
    </div>
  );
}
