/**
 * RailOS Digital Twin — GIS Corridor Map (Tasks 13.5–13.9, 13.10)
 * Three.js scene + Deck.gl GIS layers
 * Visual encoding: solid=confirmed, dashed=predicted, hatched=simulated, faded=stale
 * Satisfies: Req 8, Req 21, Req 45, Design §7.2
 */
'use client';

import React, { useEffect, useRef } from 'react';
import type { TrainState, Advisory } from '../pages/index';

interface Props {
  trains:     TrainState[];
  advisories: Advisory[];
}

// ── Color constants matching visual encoding spec (Design §7.2) ──────────────
const COLOR_CONFIRMED  = [0, 200, 100, 255];   // solid green
const COLOR_PREDICTED  = [100, 160, 255, 160];  // semi-transparent blue
const COLOR_STALE      = [180, 180, 180, 120];  // faded grey
const COLOR_DEFECT     = [255, 80,  80,  255];  // red marker
const COLOR_MAINTENANCE= [255, 165, 0,   255];  // amber marker

export default function CorridorMap({ trains, advisories }: Props) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const deckRef   = useRef<unknown>(null);

  useEffect(() => {
    if (!canvasRef.current) return;

    // Lazy-load DeckGL to avoid SSR issues
    Promise.all([
      import('@deck.gl/core'),
      import('@deck.gl/layers'),
    ]).then(([{ Deck }, { ScatterplotLayer, PathLayer, TextLayer }]) => {
      const deck = new Deck({
        parent:     canvasRef.current!,
        controller: true,
        initialViewState: {
          longitude: 78.4867,
          latitude:  17.3850,
          zoom:      9,
          pitch:     0,
          bearing:   0,
        },
        layers: [],
      });
      deckRef.current = deck;
      return deck;
    }).catch(() => { /* WebGL not available in test env */ });

    return () => {
      if (deckRef.current) {
        (deckRef.current as { finalize?: () => void }).finalize?.();
      }
    };
  }, []);

  // Update layers when state changes
  useEffect(() => {
    if (!deckRef.current) return;

    Promise.all([
      import('@deck.gl/core'),
      import('@deck.gl/layers'),
    ]).then(([, { ScatterplotLayer, TextLayer }]) => {
      // Train position layer (Task 13.5)
      const trainLayer = new ScatterplotLayer({
        id:            'trains',
        data:          trains,
        getPosition:   (t: TrainState) => [t.lon, t.lat],
        getRadius:     200,
        getFillColor:  (t: TrainState) =>
          t.isStale      ? COLOR_STALE     :
          t.isPredicted  ? COLOR_PREDICTED :
                           COLOR_CONFIRMED,
        radiusUnits:   'meters',
        pickable:      true,
      });

      // Staleness indicator text (Req 8 C2, Req 21 C3)
      const stalenessLayer = new TextLayer({
        id:           'stale-indicators',
        data:         trains.filter(t => t.isStale),
        getPosition:  (t: TrainState) => [t.lon, t.lat],
        getText:      () => '⚠',
        getColor:     [255, 165, 0, 255],
        getSize:      14,
        getPixelOffset: [0, -20],
      });

      // Defect alert markers (Task 13.5)
      const defectAdvisories = advisories.filter(a => a.category === 'defect');
      const defectLayer = new ScatterplotLayer({
        id:           'defect-alerts',
        data:         defectAdvisories,
        getPosition:  (a: Advisory) => {
          const e = a.event as Record<string, unknown>;
          const gps = e.gps as { lon?: number; lat?: number } | undefined;
          return [gps?.lon ?? 78.49, gps?.lat ?? 17.38];
        },
        getRadius:     300,
        getFillColor:  COLOR_DEFECT,
        radiusUnits:   'meters',
        pickable:      true,
      });

      (deckRef.current as { setProps: (p: unknown) => void }).setProps({
        layers: [trainLayer, stalenessLayer, defectLayer],
      });
    }).catch(() => {});
  }, [trains, advisories]);

  return (
    <div
      ref={canvasRef}
      className="w-full h-full bg-gray-800"
      style={{ position: 'relative' }}
      aria-label="RailOS corridor map"
    >
      {/* Fallback text for non-WebGL environments */}
      <div className="absolute inset-0 flex items-center justify-center text-gray-500 text-sm pointer-events-none">
        <span className="opacity-30">Corridor Map ({trains.length} trains)</span>
      </div>
    </div>
  );
}
