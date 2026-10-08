// One vehicle, drawn: a robotaxi in side view on the page's own night stage, doing whatever it is doing
// right now. Following a vehicle shows the thing itself, not a row in a list. The drawing is an SVG
// authored here, with no logo or wordmark: a low car with a sensor dome, the way driverless fleets look.
//
// Each place a vehicle can be becomes a scene: the road rolling under it, hazards blinking in the queue,
// a cable reaching for it, mint rising in its battery while it charges, a wash sweeping over it in the
// bay. Motion is CSS only, so a visitor who asks for reduced motion gets the same scene standing still.

import { PLACE } from "../trace";

export interface Shown {
  place: number;
  /** Charge as a fraction, or null on the road, where it is not recorded. */
  soc: number | null;
  kw: number | null;
  stall: number | null;
  /** Vehicles ahead in the queue for a charger, when queued. */
  ahead: number;
}

const SCENE: Record<number, string> = {
  0: "on-road",
  [PLACE.inbound]: "driving-in",
  [PLACE.queued]: "queued",
  [PLACE.pluggingIn]: "for-staff",
  [PLACE.charging]: "charging",
  [PLACE.afterCharging]: "done",
  [PLACE.cleaning]: "cleaning",
  [PLACE.outbound]: "driving-out",
};

/** What is going on, in the depot's words, for the line under the drawing. */
export function caption(shown: Shown): string {
  const pct = shown.soc === null ? "" : ` at ${Math.round(shown.soc * 100)}%`;
  switch (shown.place) {
    case 0:
      return "On the road, serving riders. The depot will call it in when its battery runs low.";
    case PLACE.inbound:
      return `Called in${pct}. Driving to the depot, a few minutes away.`;
    case PLACE.queued:
      return shown.ahead > 0 ? `Waiting for a charger${pct}, ${shown.ahead} ahead of it.` : `Waiting for a charger${pct}. One is about to free up.`;
    case PLACE.pluggingIn:
      return `Parked on a charger${pct}. Waiting for someone to plug it in.`;
    case PLACE.charging: {
      const where = shown.stall === null ? "" : ` on charger ${shown.stall + 1}`;
      const power = shown.kw === null ? "" : shown.kw >= 1 ? `, taking ${Math.round(shown.kw)} kW` : ", plugged in and waiting for power";
      return `Charging${where}${pct}${power}.`;
    }
    case PLACE.afterCharging:
      return `Full${pct}. Waiting for someone to unplug it and move it to a bay.`;
    case PLACE.cleaning:
      return `In a cleaning bay${pct}. Wiped down, checked, and sent back out.`;
    case PLACE.outbound:
      return `Leaving the depot${pct}. Back to the riders in a few minutes.`;
    default:
      return "";
  }
}

/** The drawing. One SVG, one class per scene; the scene decides which parts show and which move.
 *
 *  Side profile of a low electric crossover with a roof sensor and corner pods, shaded with gradients so
 *  it reads as a body with light on it: paint lightest along the shoulder, darker under the belt line,
 *  glass dark with a glare, wheels with depth. No fill moves inside the car; the battery bar under it
 *  carries the charge. */
export function vehicleArt(shown: Shown): string {
  const scene = SCENE[shown.place] ?? "on-road";
  const soc = shown.soc ?? 0;
  const batteryW = Math.round(92 * Math.max(0, Math.min(1, soc)));
  return `
<svg class="car-scene ${scene}" viewBox="0 0 320 150" role="img" aria-label="${caption(shown)}">
  <defs>
    <linearGradient id="paint" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff"/><stop offset="0.45" stop-color="#eef1f5"/><stop offset="0.7" stop-color="#d4dbe4"/><stop offset="1" stop-color="#b9c2ce"/>
    </linearGradient>
    <linearGradient id="paint-road" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#8ec4ff"/><stop offset="0.45" stop-color="#4f9fff"/><stop offset="0.75" stop-color="#2f7fe0"/><stop offset="1" stop-color="#1f5fb0"/>
    </linearGradient>
    <linearGradient id="glass" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#1b2c45"/><stop offset="1" stop-color="#07121f"/>
    </linearGradient>
    <linearGradient id="glare" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.35"/><stop offset="0.5" stop-color="#ffffff" stop-opacity="0.05"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="dome" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#f6f8fb"/><stop offset="1" stop-color="#aeb8c6"/>
    </linearGradient>
    <radialGradient id="tyre" cx="0.4" cy="0.35" r="0.7">
      <stop offset="0" stop-color="#3a4656"/><stop offset="0.65" stop-color="#121a26"/><stop offset="1" stop-color="#05090f"/>
    </radialGradient>
    <radialGradient id="rim" cx="0.35" cy="0.3" r="0.8">
      <stop offset="0" stop-color="#ffffff"/><stop offset="0.6" stop-color="#b8c2cf"/><stop offset="1" stop-color="#6c7886"/>
    </radialGradient>
    <linearGradient id="sill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#8e9aa9"/><stop offset="1" stop-color="#3b4654"/>
    </linearGradient>
    <filter id="soft" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="4"/></filter>
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.5"/></filter>
  </defs>

  <!-- the ground: a lane with dashes for the road scenes, a bay floor for the depot scenes -->
  <g class="ground">
    <line class="road-line" x1="0" y1="120" x2="320" y2="120"/>
    <g class="dashes"><line x1="-40" y1="120" x2="-10" y2="120"/><line x1="20" y1="120" x2="50" y2="120"/><line x1="80" y1="120" x2="110" y2="120"/><line x1="140" y1="120" x2="170" y2="120"/><line x1="200" y1="120" x2="230" y2="120"/><line x1="260" y1="120" x2="290" y2="120"/><line x1="320" y1="120" x2="350" y2="120"/></g>
    <rect class="bay-floor" x="34" y="116" width="252" height="5" rx="2.5"/>
  </g>

  <!-- the charger: a post with a cable that reaches the car when it is plugged in -->
  <g class="charger">
    <rect x="288" y="56" width="20" height="60" rx="4"/>
    <rect class="charger-screen" x="292" y="62" width="12" height="9" rx="2"/>
    <rect class="charger-lamp" x="295" y="76" width="6" height="6" rx="3"/>
    <path class="cable" d="M288 84 C274 84 268 94 260 92 L254 91"/>
    <path class="cable-loose" d="M288 84 C281 96 279 106 277 114"/>
  </g>

  <!-- the wash: an arch over the bay with water sweeping across -->
  <g class="wash">
    <path class="arch" d="M60 108 L60 34 Q60 24 70 24 L250 24 Q260 24 260 34 L260 108"/>
    <g class="spray"><line x1="104" y1="28" x2="98" y2="54"/><line x1="134" y1="28" x2="128" y2="56"/><line x1="164" y1="28" x2="158" y2="54"/><line x1="194" y1="28" x2="188" y2="56"/><line x1="224" y1="28" x2="218" y2="54"/></g>
  </g>

  <!-- the car -->
  <g class="car">
    <ellipse class="shadow" cx="162" cy="117" rx="112" ry="6" filter="url(#soft)"/>
    <!-- roof sensor: a low dome with a puck on top, and the corner pods -->
    <rect class="puck" x="148" y="28" width="22" height="7" rx="3.5"/>
    <path class="dome" d="M136 44 L136 40 Q136 33 144 33 L174 33 Q182 33 182 40 L182 44 Z"/>
    <!-- body -->
    <path class="body" d="M58 100 C52 94 52 72 60 62 C66 54 76 48 92 45 C120 40 150 40 174 42 C196 44 214 50 230 60 C244 68 258 74 270 80 C278 84 280 92 274 100 L266 102 L64 102 C60 102 58 101 58 100 Z"/>
    <!-- the shoulder highlight and the belt line -->
    <path class="shoulder" d="M64 66 C90 52 140 48 176 50 C210 52 240 62 268 80" />
    <path class="belt" d="M62 92 C110 90 200 88 272 92" />
    <!-- glass: one band, with pillars drawn in body colour over it -->
    <path class="glass" d="M86 70 L90 52 C110 46 150 44 176 46 C200 48 220 54 236 64 L244 70 Z"/>
    <path class="glare" d="M94 68 L96 54 C112 48 148 45 176 47 L180 47 L142 70 Z"/>
    <path class="pillar" d="M172 46 L170 70"/>
    <path class="pillar" d="M118 48 L112 70"/>
    <!-- door seam and sill -->
    <path class="seam" d="M170 70 L170 98"/>
    <rect class="sill" x="112" y="100" width="100" height="4" rx="2"/>
    <!-- corner pods, lamps, charge port -->
    <rect class="pod" x="60" y="56" width="12" height="9" rx="3"/>
    <rect class="pod" x="246" y="64" width="12" height="9" rx="3"/>
    <path class="lamp lamp-rear" d="M56 72 L68 70 L68 76 L56 78 Z"/>
    <path class="lamp lamp-front" d="M246 72 L270 80 L268 85 L244 78 Z"/>
    <rect class="hazard" x="56" y="80" width="10" height="6" rx="2"/>
    <rect class="hazard" x="258" y="86" width="12" height="6" rx="2"/>
    <rect class="port" x="250" y="88" width="5" height="7" rx="1.5"/>
    <!-- wheel arches, then wheels with rims -->
    <circle class="arch-cut" cx="100" cy="100" r="20"/>
    <circle class="arch-cut" cx="232" cy="100" r="20"/>
    <g class="wheel" style="transform-origin: 100px 100px"><circle class="tyre" cx="100" cy="100" r="17"/><circle class="rimface" cx="100" cy="100" r="10"/><g class="spokes"><line x1="100" y1="91" x2="100" y2="109"/><line x1="91" y1="100" x2="109" y2="100"/><line x1="93.6" y1="93.6" x2="106.4" y2="106.4"/><line x1="106.4" y1="93.6" x2="93.6" y2="106.4"/></g><circle class="hub" cx="100" cy="100" r="2.5"/></g>
    <g class="wheel" style="transform-origin: 232px 100px"><circle class="tyre" cx="232" cy="100" r="17"/><circle class="rimface" cx="232" cy="100" r="10"/><g class="spokes"><line x1="232" y1="91" x2="232" y2="109"/><line x1="223" y1="100" x2="241" y2="100"/><line x1="225.6" y1="93.6" x2="238.4" y2="106.4"/><line x1="238.4" y1="93.6" x2="225.6" y2="106.4"/></g><circle class="hub" cx="232" cy="100" r="2.5"/></g>
    <!-- motion lines behind the car on the road scenes -->
    <g class="speed"><line x1="18" y1="72" x2="46" y2="72"/><line x1="8" y1="84" x2="44" y2="84"/><line x1="24" y1="96" x2="46" y2="96"/></g>
  </g>

  <!-- the battery readout: a bar that is the car's charge, mint where the energy is -->
  <g class="battery" transform="translate(112 128)">
    <rect class="case" x="0" y="0" width="96" height="14" rx="3"/>
    <rect class="cap" x="97" y="4" width="3" height="6" rx="1"/>
    <rect class="level" x="2" y="2" width="${batteryW}" height="10" rx="2"/>
    <rect class="level-glow" x="2" y="2" width="${batteryW}" height="10" rx="2" filter="url(#glow)"/>
  </g>
</svg>`;
}
