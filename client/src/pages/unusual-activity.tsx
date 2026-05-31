import { useState, useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { AlertTriangle, User, ShieldAlert, Package, Camera } from "lucide-react";

// 🔧 UPDATE THIS every time your Cloudflare tunnel URL changes
const TUNNEL = "https://macro-divide-vacuum-lbs.trycloudflare.com";

// Playback speed options — same as recordings page
const SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2];

// ── Matches exactly what /api/alerts returns ──────────────────────────────
type Alert = {
  id:                string;
  activity_type:     string;
  timestamp:         string;
  video_file:        string;
  snapshot_filename: string;
  alert_offset_s:    number;
  severity:          "high" | "medium" | "low";
  clip_filename:     string;   // 20s clip — always playable immediately
};

// ── Build URLs ────────────────────────────────────────────────────────────
const snapshotUrl = (filename: string) =>
  `${TUNNEL}/api/alerts/snapshot/${encodeURIComponent(filename)}`;

const videoUrl = (filename: string) =>
  `${TUNNEL}/api/video/stream?file=${encodeURIComponent(filename)}`;

// 20-second alert clip — complete MP4, plays immediately (no 6h wait)
const clipUrl = (filename: string) =>
  `${TUNNEL}/api/alerts/clip/${encodeURIComponent(filename)}`;

// ── Severity → badge colour ───────────────────────────────────────────────
const getSeverityColor = (severity: string) => {
  switch (severity) {
    case "high":   return "bg-red-600 hover:bg-red-700";
    case "medium": return "bg-yellow-600 hover:bg-yellow-700";
    case "low":    return "bg-blue-600 hover:bg-blue-700";
    default:       return "";
  }
};

// ── Activity type → icon ──────────────────────────────────────────────────
const getEventIcon = (type: string) => {
  if (type.includes("Fall"))                                 return <ShieldAlert className="w-4 h-4" />;
  if (type.includes("Intrusion") || type.includes("Loiter")) return <User className="w-4 h-4" />;
  if (type.includes("Object"))                               return <Package className="w-4 h-4" />;
  if (type.includes("Tamper"))                               return <Camera className="w-4 h-4" />;
  return <AlertTriangle className="w-4 h-4" />;
};

// ── Human-readable time ───────────────────────────────────────────────────
const timeAgo = (timestamp: string) => {
  const diff = Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000);
  if (diff < 60)    return `${diff} seconds ago`;
  if (diff < 3600)  return `${Math.floor(diff / 60)} minutes ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`;
  return `${Math.floor(diff / 86400)} days ago`;
};

// ── Format seconds → hh:mm:ss ─────────────────────────────────────────────
const formatTime = (secs: number) => {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
};

// ─────────────────────────────────────────────────────────────────────────
export default function UnusualActivity() {
  const [filter, setFilter]               = useState("today");
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);

  // ── Video player state ────────────────────────────────────────────────
  const videoRef                          = useRef<HTMLVideoElement>(null);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1);
  const [clipError, setClipError]     = useState<boolean>(false);


  // Apply speed to video whenever it changes
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.playbackRate = playbackSpeed;
    }
  }, [playbackSpeed]);

  // Reset speed to 1x every time a different alert is opened
  useEffect(() => {
    setPlaybackSpeed(1);
    setClipError(false);
  }, [selectedAlert]);

  // Auto-seek: when video metadata loads → jump to (offset - 5) seconds
  // onLoadedMetadata fires as soon as the browser knows the video duration,
  // which is early enough to seek before playback begins.
  const handleVideoMetadata = () => {
    if (videoRef.current && selectedAlert) {
      const seekTo = Math.max(0, selectedAlert.alert_offset_s - 5);
      videoRef.current.currentTime = seekTo;
    }
  };

  // ── Fetch alerts from Pi ──────────────────────────────────────────────
  const { data: alerts = [], isLoading, isError } = useQuery<Alert[]>({
    queryKey: ["alerts", filter],
    queryFn: async () => {
      const res = await fetch(`${TUNNEL}/api/alerts?filter=${filter}`);
      if (!res.ok) throw new Error("Failed to fetch alerts");
      return res.json();
    },
    refetchInterval: 15_000,
    retry: false,
  });

  return (
    <div className="p-6 space-y-6">

      {/* ── Header + Filter ──────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold mb-2">Unusual Activity</h1>
          <p className="text-muted-foreground">Recent alerts and detections</p>
        </div>
        <Select value={filter} onValueChange={setFilter}>
          <SelectTrigger className="w-full sm:w-[180px]" data-testid="select-filter">
            <SelectValue placeholder="Filter by time" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="today">Today</SelectItem>
            <SelectItem value="24h">Last 24 hours</SelectItem>
            <SelectItem value="week">Last Week</SelectItem>
            <SelectItem value="all">All Time</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* ── Loading ───────────────────────────────────────────────────── */}
      {isLoading ? (
        <div className="flex justify-center py-20">
          <p className="text-muted-foreground animate-pulse">Loading alerts from Pi...</p>
        </div>

      /* ── Connection error ─────────────────────────────────────────── */
      ) : isError ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <AlertTriangle className="w-16 h-16 text-red-500 mb-4" />
            <p className="text-xl font-medium mb-2">Could not connect to Pi</p>
            <p className="text-muted-foreground">Check your tunnel URL and Pi connection.</p>
          </CardContent>
        </Card>

      /* ── No alerts for this period ────────────────────────────────── */
      ) : alerts.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <AlertTriangle className="w-16 h-16 text-muted-foreground mb-4" />
            <p className="text-xl font-medium mb-2">No alerts found</p>
            <p className="text-muted-foreground">No unusual activity detected for this period.</p>
          </CardContent>
        </Card>

      /* ── Alert Cards Grid ─────────────────────────────────────────── */
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {alerts.map((alert) => (
            <Card
              key={alert.id}
              className="cursor-pointer hover-elevate active-elevate-2 overflow-visible"
              onClick={() => setSelectedAlert(alert)}
              data-testid={`card-alert-${alert.id}`}
            >
              <CardContent className="p-4 space-y-3">

                {/* Snapshot thumbnail */}
                <div className="relative aspect-video bg-black rounded-md overflow-hidden">
                  <img
                    src={snapshotUrl(alert.snapshot_filename)}
                    alt={alert.activity_type}
                    className="w-full h-full object-cover"
                    data-testid={`img-alert-${alert.id}`}
                  />
                </div>

                {/* Badge + metadata */}
                <div className="space-y-2">
                  <Badge variant="default" className={getSeverityColor(alert.severity)}>
                    {getEventIcon(alert.activity_type)}
                    <span className="ml-1">{alert.activity_type}</span>
                  </Badge>
                  <div className="text-sm text-muted-foreground">
                    <p data-testid={`text-camera-${alert.id}`}>
                      Camera 01 - Main Entrance
                    </p>
                    <p data-testid={`text-timestamp-${alert.id}`}>
                      {timeAgo(alert.timestamp)}
                    </p>
                  </div>
                </div>

              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* ── Alert Detail Dialog ───────────────────────────────────────── */}
      <Dialog open={!!selectedAlert} onOpenChange={() => setSelectedAlert(null)}>
        <DialogContent className="max-w-4xl w-full p-0 bg-black border-none">

          <DialogHeader className="p-6 pb-4 bg-background">
            <DialogTitle>{selectedAlert?.activity_type}</DialogTitle>
            <DialogDescription>
              Camera 01 - Main Entrance &nbsp;•&nbsp; {selectedAlert?.timestamp}
            </DialogDescription>
          </DialogHeader>

          {selectedAlert && (
            <div className="px-6 pb-6 bg-background space-y-4">

              {/* ── Video Player ─────────────────────────────────────── */}
              {/*
                Priority order:
                  1. clip_filename set  → 20s clip  (current session alert — clip always playable)
                  2. video_file set     → main recording + auto-seek  (old session — file is complete)
                  3. neither            → snapshot image only
              */}
              <div className="relative aspect-video bg-black rounded-md overflow-hidden">
                {selectedAlert.clip_filename && !clipError ? (
                  /*
                    CURRENT SESSION ALERT:
                    Play the 20-second clip saved at alert time.
                    Clip starts 5s BEFORE the alert — play from beginning, no seeking needed.
                    This is a complete MP4 file, always playable immediately.
                  */
                  <video
                    ref={videoRef}
                    controls
                    autoPlay
                    crossOrigin="anonymous"
                    className="w-full h-full"
                    key={selectedAlert.clip_filename}
                    onError={() => setClipError(true)}
                  >
                    <source
                      src={clipUrl(selectedAlert.clip_filename)}
                      type="video/mp4"
                    />
                    Your browser does not support the video tag.
                  </video>
                ) : selectedAlert.video_file ? (
                  /*
                    OLD SESSION ALERT:
                    The recording segment is complete (finalized by ffmpeg after 6h).
                    Use the full recording + auto-seek to alert_offset_s - 5 seconds.
                    This is the original offset-based approach that always worked for old alerts.
                  */
                  <video
                    ref={videoRef}
                    controls
                    autoPlay
                    crossOrigin="anonymous"
                    className="w-full h-full"
                    key={selectedAlert.video_file}
                    onLoadedMetadata={handleVideoMetadata}
                  >
                    <source
                      src={videoUrl(selectedAlert.video_file)}
                      type="video/mp4"
                    />
                    Your browser does not support the video tag.
                  </video>
                ) : (
                  /* No video available — show snapshot only */
                  <img
                    src={snapshotUrl(selectedAlert.snapshot_filename)}
                    alt={selectedAlert.activity_type}
                    className="w-full h-full object-cover"
                    data-testid="img-modal-alert"
                  />
                )}
              </div>

              {/* ── Info Banner ──────────────────────────────────────── */}
              {selectedAlert.clip_filename ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/50 rounded px-3 py-2">
                  <span>🎬</span>
                  <span>
                    Playing <strong>20-second alert clip</strong>
                    &nbsp;— starts 5 seconds before the event
                  </span>
                </div>
              ) : selectedAlert.video_file ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/50 rounded px-3 py-2">
                  <span>⏱</span>
                  <span>
                    Auto-seeking to <strong>{formatTime(Math.max(0, selectedAlert.alert_offset_s - 5))}</strong>
                    &nbsp;— 5 seconds before alert at <strong>{formatTime(selectedAlert.alert_offset_s)}</strong>
                  </span>
                </div>
              ) : null}

              {/* ── Speed Control ─────────────────────────────────────── */}
              {(selectedAlert.clip_filename || selectedAlert.video_file) && (
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="text-sm font-medium text-muted-foreground whitespace-nowrap">
                    Playback Speed:
                  </span>
                  <div className="flex items-center gap-2 flex-wrap">
                    {SPEED_OPTIONS.map((speed) => (
                      <Button
                        key={speed}
                        size="sm"
                        variant={playbackSpeed === speed ? "default" : "outline"}
                        onClick={() => setPlaybackSpeed(speed)}
                        className={
                          playbackSpeed === speed
                            ? "bg-primary text-primary-foreground font-semibold min-w-[52px]"
                            : "min-w-[52px]"
                        }
                      >
                        {speed}x
                      </Button>
                    ))}
                  </div>
                </div>
              )}

              {/* ── Alert Metadata Grid ───────────────────────────────── */}
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-muted-foreground">Event Type</p>
                  <p className="font-medium">{selectedAlert.activity_type}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Severity</p>
                  <Badge className={getSeverityColor(selectedAlert.severity)}>
                    {selectedAlert.severity.toUpperCase()}
                  </Badge>
                </div>
                <div>
                  <p className="text-muted-foreground">Timestamp</p>
                  <p className="font-medium">{selectedAlert.timestamp}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Camera</p>
                  <p className="font-medium">Camera 01 - Main Entrance</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Recording File</p>
                  <p className="font-medium text-xs overflow-hidden text-ellipsis">
                    {selectedAlert.video_file || "—"}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">Alert at</p>
                  <p className="font-medium">
                    {formatTime(selectedAlert.alert_offset_s)} into recording
                  </p>
                </div>
              </div>

            </div>
          )}

        </DialogContent>
      </Dialog>

    </div>
  );
}
