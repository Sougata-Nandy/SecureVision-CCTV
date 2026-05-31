import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Maximize, Minimize, Pause, Play, Camera } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import videoPlaceholder from "@assets/generated_images/CCTV_video_feed_placeholder_a43eaddb.png";
import { useLocation } from "wouter";

// 🔧 UPDATE THIS every time your Cloudflare tunnel URL changes
const TUNNEL = "https://macro-divide-vacuum-lbs.trycloudflare.com";

// How often to fetch a new frame (ms). 200ms = 5fps.
// Lower = smoother but more requests. 150ms = ~6fps max.
const POLL_INTERVAL = 200;

type LiveFeedProps = {
  onFullscreenChange?: (isFullscreen: boolean) => void;
};

export default function LiveFeed({ onFullscreenChange }: LiveFeedProps) {
  const [, setLocation] = useLocation();

  useEffect(() => {
    const user = localStorage.getItem("user");
    if (!user) setLocation("/login");
  }, []);

  const { toast } = useToast();
  const [isPlaying,    setIsPlaying]    = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isOnline,     setIsOnline]     = useState(false);
  const [imgSrc,       setImgSrc]       = useState<string>("");

  const imgRef            = useRef<HTMLImageElement>(null);
  const videoContainerRef = useRef<HTMLDivElement>(null);
  const timerRef          = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playingRef        = useRef(true);   // ref so fetchFrame closure sees latest value
  const errorCountRef     = useRef(0);

  // ---------------------------------------------------------------------------
  // Snapshot polling loop
  //
  // How it works:
  //   1. Request GET /snapshot?t=<timestamp> (cache-buster prevents browser cache)
  //   2. On load: schedule next fetch after POLL_INTERVAL ms
  //   3. On error: back off for 1s, then retry
  //
  // Why not HLS:
  //   libx264 software encoding consumed >80% CPU on the Pi even at 8fps,
  //   leaving the stream running at 0.17x realtime (fast-forward + freeze).
  //   JPEG encoding takes ~2ms vs ~50ms for H264, so the Pi handles it easily.
  // ---------------------------------------------------------------------------
  const fetchFrame = useCallback(() => {
    if (!playingRef.current) return;
    setImgSrc(`${TUNNEL}/snapshot?t=${Date.now()}`);
  }, []);

  const scheduleNext = useCallback(() => {
    timerRef.current = setTimeout(fetchFrame, POLL_INTERVAL);
  }, [fetchFrame]);

  const startPolling = useCallback(() => {
    playingRef.current = true;
    fetchFrame();
  }, [fetchFrame]);

  const stopPolling = useCallback(() => {
    playingRef.current = false;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  const handleImgLoad = () => {
    errorCountRef.current = 0;
    setIsOnline(true);
    scheduleNext();   // only schedule next frame after current one loaded
  };

  const handleImgError = () => {
    errorCountRef.current += 1;
    if (errorCountRef.current >= 3) setIsOnline(false);
    // Back off 1s on error before retrying
    timerRef.current = setTimeout(fetchFrame, 1000);
  };

  // Fullscreen
  useEffect(() => {
    const onChange = () => {
      const fs = !!document.fullscreenElement;
      setIsFullscreen(fs);
      onFullscreenChange?.(fs);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [onFullscreenChange]);

  const handleFullscreen = async () => {
    try {
      if (!document.fullscreenElement) {
        await videoContainerRef.current?.requestFullscreen();
        toast({ title: "Fullscreen", description: "Entering fullscreen mode..." });
      } else {
        await document.exitFullscreen();
        toast({ title: "Normal view", description: "Exiting fullscreen mode..." });
      }
    } catch { }
  };

  const handlePause = () => {
    if (isPlaying) {
      stopPolling();
    } else {
      startPolling();
    }
    setIsPlaying(p => !p);
    toast({
      title:       isPlaying ? "Paused" : "Playing",
      description: `Video feed ${isPlaying ? "paused" : "resumed"}`,
    });
  };

  const handleSnapshot = () => {
    // Create a canvas, draw the current img element, download as JPEG
    if (!imgRef.current || !imgRef.current.complete) return;
    const canvas = document.createElement("canvas");
    canvas.width  = imgRef.current.naturalWidth  || 640;
    canvas.height = imgRef.current.naturalHeight || 480;
    canvas.getContext("2d")?.drawImage(imgRef.current, 0, 0);
    const link = document.createElement("a");
    link.download = `snapshot_${Date.now()}.jpg`;
    link.href = canvas.toDataURL("image/jpeg", 0.92);
    link.click();
    toast({ title: "Snapshot captured", description: "Image downloaded to your device" });
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-3xl font-semibold mb-2">Live Feed</h1>
        <p className="text-muted-foreground">Real-time surveillance monitoring</p>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0 pb-4">
          <CardTitle className="text-xl">Camera 01 - Main Entrance</CardTitle>
          <div className="flex items-center gap-4">
            {isOnline ? (
              <Badge variant="default" className="bg-green-600 hover:bg-green-700" data-testid="badge-status">
                <span className="w-2 h-2 bg-white rounded-full mr-2 animate-pulse" />
                Live
              </Badge>
            ) : (
              <Badge variant="destructive" data-testid="badge-status">
                Connecting...
              </Badge>
            )}
            <span className="text-sm text-muted-foreground" data-testid="text-fps">~5 FPS</span>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div
            ref={videoContainerRef}
            className="relative aspect-video bg-black rounded-md overflow-hidden border border-gray-700"
          >
            {/*
              Each poll fetches /snapshot?t=<ms> — the ?t= is a cache-buster.
              onLoad fires when the image is fully decoded, then schedules
              the next fetch. This chain means frames arrive as fast as the
              network + Pi can serve them, with no buffering or queuing.
            */}
            {imgSrc && (
              <img
                ref={imgRef}
                src={imgSrc}
                alt="Live CCTV Feed"
                className="w-full h-full object-contain"
                onLoad={handleImgLoad}
                onError={handleImgError}
              />
            )}

            {!isOnline && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80">
                <img src={videoPlaceholder} alt="Offline"
                  className="w-32 h-32 object-contain opacity-30 mb-4" />
                <p className="text-white text-lg font-semibold">Connecting to camera...</p>
                <p className="text-gray-400 text-sm mt-1">Stream initializing, please wait</p>
              </div>
            )}

            {!isPlaying && isOnline && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                <p className="text-white text-lg font-semibold">Feed Paused</p>
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <Button onClick={handleFullscreen} data-testid="button-fullscreen">
              {isFullscreen
                ? <><Minimize className="w-4 h-4 mr-2" />Minimize</>
                : <><Maximize className="w-4 h-4 mr-2" />Fullscreen</>}
            </Button>
            <Button variant="outline" onClick={handlePause} data-testid="button-pause">
              {isPlaying
                ? <><Pause className="w-4 h-4 mr-2" />Pause</>
                : <><Play  className="w-4 h-4 mr-2" />Play</>}
            </Button>
            <Button variant="outline" onClick={handleSnapshot} data-testid="button-snapshot">
              <Camera className="w-4 h-4 mr-2" />Snapshot
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
