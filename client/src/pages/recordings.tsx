import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Eye, Download, Film, X, HardDrive, AlertTriangle, CheckCircle } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useLocation } from "wouter";
import { useQuery } from "@tanstack/react-query";

// Automatically uses the same origin the page was loaded from.
// Works on local network and Cloudflare tunnel without any hardcoding.
const TUNNEL = "https://macro-divide-vacuum-lbs.trycloudflare.com";

// All available playback speeds — shown as buttons in the video dialog
const SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2];

type Recording = {
  id:       string;
  filename: string;
  date:     string;
  duration: string;
  camera:   string;
  size:     string;
  status:   "recording" | "completed";
};

type StorageInfo = {
  total_gb:     number;
  used_gb:      number;
  free_gb:      number;
  percent_used: number;
  health:       "ok" | "warning" | "critical";
  error?:       string;
};

// ---------------------------------------------------------------------------
// Storage Status Card
// ---------------------------------------------------------------------------
function StorageStatus() {
  const { data: storage, isLoading } = useQuery<StorageInfo>({
    queryKey: ["storage"],
    queryFn: async () => {
      const res = await fetch(`${TUNNEL}/api/storage`);
      if (!res.ok) throw new Error("Failed");
      return res.json();
    },
    refetchInterval: 30_000,   // refresh every 30 seconds
    retry: false,
  });

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-4 flex items-center gap-3">
          <HardDrive className="w-5 h-5 text-muted-foreground animate-pulse" />
          <span className="text-sm text-muted-foreground">Checking storage...</span>
        </CardContent>
      </Card>
    );
  }

  if (!storage || storage.error) {
    return (
      <Card>
        <CardContent className="p-4 flex items-center gap-3">
          <HardDrive className="w-5 h-5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">Storage info unavailable</span>
        </CardContent>
      </Card>
    );
  }

  const barColor =
    storage.health === "critical" ? "bg-red-500" :
    storage.health === "warning"  ? "bg-yellow-500" :
                                    "bg-green-500";

  const textColor =
    storage.health === "critical" ? "text-red-600" :
    storage.health === "warning"  ? "text-yellow-600" :
                                    "text-green-600";

  const Icon =
    storage.health === "critical" ? AlertTriangle :
    storage.health === "warning"  ? AlertTriangle :
                                    CheckCircle;

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <HardDrive className="w-5 h-5 text-muted-foreground" />
            <span className="text-sm font-medium">SSD Storage</span>
          </div>
          <div className={`flex items-center gap-1 text-sm font-semibold ${textColor}`}>
            <Icon className="w-4 h-4" />
            {storage.percent_used}% used
          </div>
        </div>

        {/* Progress bar */}
        <div className="w-full bg-muted rounded-full h-2.5 mb-2 overflow-hidden">
          <div
            className={`h-2.5 rounded-full transition-all duration-500 ${barColor}`}
            style={{ width: `${Math.min(storage.percent_used, 100)}%` }}
          />
        </div>

        <div className="flex justify-between text-xs text-muted-foreground">
          <span>{storage.used_gb} GB used</span>
          <span>{storage.free_gb} GB free / {storage.total_gb} GB total</span>
        </div>

        {storage.health === "critical" && (
          <p className="mt-2 text-xs text-red-600 font-medium">
            ⚠ Disk almost full — oldest recordings will be auto-deleted soon.
          </p>
        )}
        {storage.health === "warning" && (
          <p className="mt-2 text-xs text-yellow-600 font-medium">
            Disk filling up — auto-cleanup will trigger at 90%.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main Recordings Page
// ---------------------------------------------------------------------------
export default function Recordings() {
  const { toast } = useToast();
  const [, setLocation] = useLocation();
  const [selectedRecording, setSelectedRecording] = useState<Recording | null>(null);

  // ── Speed control ───────────────────────────────────────────────────────
  const videoRef                          = useRef<HTMLVideoElement>(null);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1);

  // Apply speed to video element instantly whenever the button is clicked
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.playbackRate = playbackSpeed;
    }
  }, [playbackSpeed]);

  // Reset speed back to 1x every time a new recording is opened
  useEffect(() => {
    setPlaybackSpeed(1);
  }, [selectedRecording]);

  const { data: recordings = [], isLoading } = useQuery<Recording[]>({
    queryKey: ["recordings"],
    queryFn: async () => {
      const res = await fetch(`${TUNNEL}/api/recordings`);
      if (!res.ok) throw new Error("Failed to fetch recordings");
      return res.json();
    },
    refetchInterval: 10_000,
  });

  const videoUrl = (filename: string) =>
    `${TUNNEL}/api/video/stream?file=${encodeURIComponent(filename)}`;

  const getMime = (filename: string) =>
    filename.endsWith(".mp4") ? "video/mp4" : "video/x-msvideo";

  const handleView = (r: Recording) => setSelectedRecording(r);

  const handleDownload = async (r: Recording) => {
    toast({ title: "Download starting...", description: r.filename });
    try {
      const res = await fetch(videoUrl(r.filename));
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href = url; a.download = r.filename;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast({ title: "Download complete", description: r.filename });
    } catch {
      toast({ title: "Download failed", description: "Check tunnel connection.", variant: "destructive" });
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-3xl font-semibold mb-2">Recordings</h1>
        <p className="text-muted-foreground">Past surveillance recordings from SSD</p>
      </div>

      {/* Storage Status */}
      <StorageStatus />

      {isLoading ? (
        <div className="flex justify-center py-20">
          <p className="text-muted-foreground animate-pulse">Loading recordings from Pi SSD...</p>
        </div>
      ) : recordings.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Film className="w-16 h-16 text-muted-foreground mb-4" />
            <p className="text-xl font-medium mb-2">No recordings available</p>
            <p className="text-muted-foreground">Check if your SSD is mounted correctly.</p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Desktop */}
          <div className="hidden md:block">
            <Card>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="border-b bg-muted/50">
                      <tr>
                        <th className="px-6 py-3 text-left text-sm font-medium">Date & Time</th>
                        <th className="px-6 py-3 text-left text-sm font-medium">Camera</th>
                        <th className="px-6 py-3 text-left text-sm font-medium">Duration</th>
                        <th className="px-6 py-3 text-left text-sm font-medium">Size</th>
                        <th className="px-6 py-3 text-left text-sm font-medium">Status</th>
                        <th className="px-6 py-3 text-right text-sm font-medium">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {recordings.map((r) => (
                        <tr key={r.id} className="hover:bg-muted/50 transition-colors">
                          <td className="px-6 py-4 text-sm">{r.date}</td>
                          <td className="px-6 py-4 text-sm">{r.camera}</td>
                          <td className="px-6 py-4 text-sm">{r.duration}</td>
                          <td className="px-6 py-4 text-sm text-muted-foreground">{r.size}</td>
                          <td className="px-6 py-4 text-sm">
                            {r.status === "recording" ? (
                              <Badge className="bg-red-600 hover:bg-red-700 text-white">
                                <span className="w-2 h-2 bg-white rounded-full mr-1 animate-pulse" />
                                Recording
                              </Badge>
                            ) : (
                              <Badge variant="secondary">Completed</Badge>
                            )}
                          </td>
                          <td className="px-6 py-4 text-right">
                            <div className="flex items-center justify-end gap-2">
                              {r.status === "recording" ? (
                                /* File is being written — moov atom not yet finalized.
                                   Redirect to Live Feed page which uses JPEG snapshots. */
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="border-green-600 text-green-600 hover:bg-green-50"
                                  onClick={() => setLocation("/")}
                                  title="Recording in progress — watch live instead"
                                >
                                  <Eye className="w-4 h-4 mr-1" /> Live Feed
                                </Button>
                              ) : (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => handleView(r)}
                                >
                                  <Eye className="w-4 h-4 mr-1" /> View
                                </Button>
                              )}
                              <Button variant="outline" size="sm" onClick={() => handleDownload(r)}>
                                <Download className="w-4 h-4 mr-1" /> Download
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Mobile */}
          <div className="md:hidden space-y-4">
            {recordings.map((r) => (
              <Card key={r.id}>
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="font-medium">{r.camera}</p>
                    {r.status === "recording" ? (
                      <Badge className="bg-red-600 text-white text-xs">
                        <span className="w-1.5 h-1.5 bg-white rounded-full mr-1 animate-pulse" />Live
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="text-xs">Done</Badge>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground">{r.date}</p>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">{r.duration}</span>
                    <span className="text-muted-foreground">{r.size}</span>
                  </div>
                  <div className="flex gap-2">
                    {r.status === "recording" ? (
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1 border-green-600 text-green-600"
                        onClick={() => setLocation("/")}
                        title="Recording in progress — watch live"
                      >
                        <Eye className="w-4 h-4 mr-1" /> Live Feed
                      </Button>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1"
                        onClick={() => handleView(r)}
                      >
                        <Eye className="w-4 h-4 mr-1" /> View
                      </Button>
                    )}
                    <Button variant="outline" size="sm" className="flex-1" onClick={() => handleDownload(r)}>
                      <Download className="w-4 h-4 mr-1" /> Download
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}

      {/* Playback Dialog */}
      <Dialog open={!!selectedRecording} onOpenChange={() => setSelectedRecording(null)}>
        <DialogContent className="max-w-4xl w-full p-0 bg-black border-none">
          <DialogHeader className="p-6 pb-4 bg-background">
            <div className="flex items-center justify-between">
              <DialogTitle className="text-xl">{selectedRecording?.camera}</DialogTitle>
              <Button variant="ghost" size="icon" onClick={() => setSelectedRecording(null)}>
                <X className="w-4 h-4" />
              </Button>
            </div>
            <p className="text-sm text-muted-foreground">
              {selectedRecording?.date} • {selectedRecording?.duration}
            </p>
          </DialogHeader>

          <div className="px-6 pb-6 bg-background space-y-4">
            {/* Video Player */}
            <div className="relative aspect-video bg-black rounded-md overflow-hidden">
              {selectedRecording && (
                <video
                  ref={videoRef}
                  controls
                  autoPlay
                  crossOrigin="anonymous"
                  className="w-full h-full"
                  key={selectedRecording.filename}
                >
                  <source
                    src={videoUrl(selectedRecording.filename)}
                    type={getMime(selectedRecording.filename)}
                  />
                  Your browser does not support the video tag.
                </video>
              )}
            </div>

            {/* ── Speed Control Bar ──────────────────────────────────────── */}
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
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
