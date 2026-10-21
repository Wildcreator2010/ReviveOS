"use client";

import { useEffect } from "react";

/**
 * Two details borrowed from wildcreator.top: a soft cursor ring and a card
 * spotlight that follows the pointer. Both are disabled for touch/reduced-motion.
 */
export function PointerEffects() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const fine = window.matchMedia("(pointer: fine)").matches;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!fine || reduced) return;

    const dot = document.createElement("div");
    dot.className = "cursor-dot";
    const ring = document.createElement("div");
    ring.className = "cursor-ring";
    document.body.append(dot, ring);
    document.body.classList.add("has-pointer-effects");

    let mouseX = window.innerWidth / 2;
    let mouseY = window.innerHeight / 2;
    let ringX = mouseX;
    let ringY = mouseY;
    let frame = 0;

    const onMove = (event: PointerEvent) => {
      mouseX = event.clientX;
      mouseY = event.clientY;
      dot.style.opacity = "1";
      ring.style.opacity = "1";
      dot.style.transform = `translate(${mouseX}px, ${mouseY}px) translate(-50%, -50%)`;
      const card = (event.target as Element | null)?.closest?.(".panel, .tile, .list-item");
      if (card instanceof HTMLElement) {
        const bounds = card.getBoundingClientRect();
        card.style.setProperty("--mx", ((event.clientX - bounds.left) / bounds.width).toFixed(3));
        card.style.setProperty("--my", ((event.clientY - bounds.top) / bounds.height).toFixed(3));
      }
    };
    const tick = () => {
      ringX += (mouseX - ringX) * 0.18;
      ringY += (mouseY - ringY) * 0.18;
      ring.style.transform = `translate(${ringX}px, ${ringY}px) translate(-50%, -50%)`;
      frame = window.requestAnimationFrame(tick);
    };
    const onLeave = () => {
      dot.style.opacity = "0";
      ring.style.opacity = "0";
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    frame = window.requestAnimationFrame(tick);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      document.body.classList.remove("has-pointer-effects");
      dot.remove();
      ring.remove();
    };
  }, []);

  return null;
}
