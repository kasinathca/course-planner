import { textElement } from "../api.js";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const PALETTE = [
  ["#dbe8ff", "#2457c5"], ["#dff4e7", "#247047"], ["#fbe5d6", "#9a4f16"],
  ["#eee2fa", "#7540a8"], ["#d9f0f0", "#176b70"], ["#f9dfeb", "#9d3562"],
  ["#fff0c9", "#8a6200"], ["#e4e8ef", "#4b5870"],
];

export function renderTimetable(result, onMeeting) {
  const grid = document.querySelector("#timetable-grid");
  const empty = document.querySelector("#timetable-empty");
  const panel = document.querySelector("#meeting-list-panel");
  const legend = document.querySelector("#timetable-legend");
  if (!result) {
    grid.hidden = true; panel.hidden = true; legend.hidden = true; empty.hidden = false; return;
  }
  const meetings = result.assignments.flatMap((assignment) => assignment.meetings.map((meeting) => ({ ...meeting, course_code: assignment.course_code })));
  meetings.sort((a, b) => a.day - b.day || a.start_minute - b.start_minute || a.course_code.localeCompare(b.course_code));
  if (!meetings.length) {
    grid.hidden = true; panel.hidden = false; empty.hidden = false;
    empty.innerHTML = "<strong>No physical meetings.</strong><span>This result may contain NIL-slot or online administrative components only.</span>";
    renderMeetingTable(meetings); return;
  }
  empty.hidden = true; grid.hidden = false; panel.hidden = false; legend.hidden = false;
  const first = Math.floor(Math.min(...meetings.map((item) => item.start_minute)) / 60) * 60;
  const last = Math.ceil(Math.max(...meetings.map((item) => item.end_minute)) / 60) * 60;
  const duration = Math.max(60, last - first); const laneHeight = duration;
  grid.style.setProperty("--day-count", "7"); grid.style.setProperty("--lane-height", `${laneHeight}px`); grid.style.setProperty("--hour-height", "60px");
  const head = document.createElement("div"); head.className = "timetable-head"; head.append(document.createElement("div"));
  for (const day of DAYS) head.append(textElement("div", day));
  const body = document.createElement("div"); body.className = "timetable-body";
  const axis = document.createElement("div"); axis.className = "time-axis";
  for (let minute = first; minute <= last; minute += 60) {
    const label = textElement("span", clock(minute), "time-label"); label.style.top = `${minute - first}px`; axis.append(label);
  }
  body.append(axis);
  const codes = [...new Set(meetings.map((item) => item.course_code))];
  for (let day = 0; day < 7; day += 1) {
    const lane = document.createElement("div"); const dayMeetings = meetings.filter((item) => item.day === day);
    lane.className = `day-lane${dayMeetings.length ? "" : " empty"}`;
    for (const meeting of dayMeetings) {
      const button = document.createElement("button"); const colors = PALETTE[hash(meeting.course_code) % PALETTE.length];
      button.type = "button"; button.className = `meeting-block ${meeting.kind}`;
      button.style.top = `${meeting.start_minute - first}px`; button.style.height = `${Math.max(18, meeting.end_minute - meeting.start_minute)}px`;
      button.style.setProperty("--course-color", colors[0]); button.style.setProperty("--course-accent", colors[1]);
      button.setAttribute("aria-label", `${meeting.course_code}, ${meeting.component_type}, ${DAYS[meeting.day]} ${clock(meeting.start_minute)} to ${clock(meeting.end_minute)}, ${meeting.faculty}, ${meeting.venue}`);
      button.append(textElement("strong", `${meeting.course_code} · ${meeting.component_type}`), textElement("span", `${clock(meeting.start_minute)}–${clock(meeting.end_minute)}`, "meeting-time"), textElement("span", meeting.faculty || "Faculty not supplied"));
      button.addEventListener("click", () => onMeeting(meeting)); lane.append(button);
    }
    body.append(lane);
  }
  grid.replaceChildren(head, body); renderMeetingTable(meetings);
  legend.replaceChildren(...codes.map((code) => {
    const colors = PALETTE[hash(code) % PALETTE.length]; const item = document.createElement("span");
    const swatch = document.createElement("i"); swatch.style.setProperty("--course-color", colors[0]); item.append(swatch, code); return item;
  }));
}

function renderMeetingTable(meetings) {
  const body = document.querySelector("#meeting-list-body");
  body.replaceChildren(...meetings.map((item) => {
    const row = document.createElement("tr"); row.append(textElement("td", DAYS[item.day]), textElement("td", `${clock(item.start_minute)}–${clock(item.end_minute)} (${item.end_minute - item.start_minute} min)`), textElement("td", item.course_code), textElement("td", item.component_type), textElement("td", item.faculty), textElement("td", item.venue), textElement("td", item.slot)); return row;
  }));
  if (!meetings.length) { const row = document.createElement("tr"); const cell = textElement("td", "No physical meetings in this result.", "empty-cell"); cell.colSpan = 7; row.append(cell); body.append(row); }
}

export function clock(minute) { const hours = Math.floor(minute / 60); return `${String(hours).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`; }
function hash(value) { return [...value].reduce((total, character) => ((total * 31) + character.charCodeAt(0)) >>> 0, 0); }
