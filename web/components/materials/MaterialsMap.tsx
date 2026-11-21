"use client";

import { useEffect, useRef, useState } from "react";

import { layoutMap, type MapLabel, type MaterialsModel } from "@/lib/materials-map";

/**
 * The materials line map. Every extracted program is a line: they run together through one capsule per
 * material all of them ask for, split at 45 degrees, and each then stops only where its own page asks
 * for something. Inside a capsule, a line whose program asks in a form of its own carries the
 * highlighter. A program whose page has not been read, or was read and lists no documents, is a dotted
 * run beside them that joins nothing.
 *
 * The drawing is a picture of the lists under it and carries no control: its accessible name says what
 * is shared and what differs, and the ticks are in those lists. A wide frame draws it left to right, a
 * narrow one top to bottom (lib/materials-map.ts decides, from the frame's own width).
 */
export function MaterialsMap({ model, selected }: { model: MaterialsModel; selected: string | null }) {
  const frame = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    const read = () => setWidth(Math.floor(node.clientWidth));
    read();
    const observer = new ResizeObserver(read);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const map = width > 0 ? layoutMap(model, width) : null;
  const dim = (id: string | undefined) => (selected && id ? (id === selected ? " is-sel" : " is-dim") : "");

  return (
    <div className="map-frame" ref={frame}>
      {map && (
        <div
          className={`map${map.vertical ? " is-vertical" : ""}`}
          role="img"
          aria-label={describe(model)}
          style={{ width: map.vertical ? map.width : undefined, height: map.height }}
        >
          <svg viewBox={`0 0 ${map.width} ${map.height}`} aria-hidden="true" focusable="false">
            {map.guides.map((guide, index) => (
              <line key={index} className="guide" {...guide} />
            ))}
            {map.dotted.map(({ line, d }) => (
              <path key={line.record.id} className={`ln is-unread line-${line.line}${dim(line.record.id)}`} d={d} />
            ))}
            {map.paths.map(({ line, d }) => (
              <path key={line.record.id} className={`ln line-${line.line}${dim(line.record.id)}`} d={d} />
            ))}
            {map.hubs.map(({ column, ready, ...box }) => (
              <rect key={column.type} className={`hub${ready ? " is-ready" : ""}`} rx={8} {...box} />
            ))}
            {map.hubMarks.map(({ requirement, ...box }) => (
              <rect
                key={`${requirement.line.record.id}:${requirement.entries[0].type}`}
                className={`hub-mark${dim(requirement.line.record.id)}`}
                rx={3}
                {...box}
              />
            ))}
            {map.stations.map(({ requirement, x, y }) => (
              <circle
                key={`${requirement.line.record.id}:${requirement.entries[0].key}`}
                className={`stn line-${requirement.line.line}${requirement.ready ? " is-ready" : ""}${requirement.differs ? " is-diff" : ""}${dim(requirement.line.record.id)}`}
                cx={x}
                cy={y}
                r={6.5}
              />
            ))}
          </svg>
          {map.labels.map((label, index) => (
            <Label key={index} label={label} dim={dim(label.line?.record.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

/** A label's class is `lbl-<kind>`: bare `end` and `group` are utility names in the project's Tailwind build. */
function Label({ label, dim }: { label: MapLabel; dim: string }) {
  const position = { left: label.x, top: label.y };
  if (label.kind === "end") {
    return (
      <span className={`lbl lbl-end a-${label.align} line-${label.line!.line}${dim}`} style={position}>
        <span className="bullet">{label.text}</span>
      </span>
    );
  }
  return (
    <span className={`lbl lbl-${label.kind} a-${label.align}${label.differs ? " is-diff" : ""}${dim}`} style={position}>
      {label.text}
    </span>
  );
}

/** What the picture shows, in a sentence, for a reader who cannot see it. */
function describe(model: MaterialsModel): string {
  const parts: string[] = [];
  const names = (columns: MaterialsModel["shared"]) => columns.map((column) => column.name).join("、");
  const same = model.shared.filter((column) => column.uniform);
  const mixed = model.shared.filter((column) => !column.uniform);
  if (same.length) parts.push(`${names(same)}，${model.lines.length} 个项目都要，要求一样`);
  // Asked by all is all that is claimed here; who asks what is in the list.
  if (mixed.length) parts.push(`${names(mixed)}，${model.lines.length} 个项目都要，要求不完全一样`);
  if (model.differing.length) {
    const columns = names(model.differing);
    // With one program read there is nothing to differ from: the columns are simply what it asks for.
    parts.push(model.lines.length > 1 ? `${columns}各项目要求不同` : `${model.lines[0].record.school}要交${columns}`);
  }
  if (model.unread.length) parts.push(`${model.unread.map((line) => line.record.school).join("、")}的要求还没提取`);
  if (model.silent.length) parts.push(`${model.silent.map((line) => line.record.school).join("、")}的项目页没有列申请材料`);
  return parts.length ? `线路图：${parts.join("；")}。详见下方清单。` : "线路图：还没有可画的要求。";
}
