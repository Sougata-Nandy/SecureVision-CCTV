import type { Express } from "express";
import { createServer, type Server } from "http";
import { storage } from "./storage";
import { promises as fs } from "fs";
import { createReadStream } from "fs";
import path from "path";

export async function registerRoutes(app: Express): Promise<Server> {
  // API endpoint to get video file size
  app.get("/api/video/size", async (req, res) => {
    try {
      const videoPath = path.join(process.cwd(), "attached_assets", "videos", "demo.mp4");
      const stats = await fs.stat(videoPath);
      const fileSizeInBytes = stats.size;
      const fileSizeInMB = (fileSizeInBytes / (1024 * 1024)).toFixed(2);
      
      res.json({
        sizeBytes: fileSizeInBytes,
        sizeMB: fileSizeInMB,
        sizeFormatted: fileSizeInBytes >= 1024 * 1024 * 1024 
          ? `${(fileSizeInBytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
          : `${fileSizeInMB} MB`
      });
    } catch (error) {
      res.status(404).json({ error: "Video file not found" });
    }
  });

  // Serve video file with range request support for streaming
  app.get("/api/video/stream", async (req, res) => {
    try {
      const videoPath = path.join(process.cwd(), "attached_assets", "videos", "demo.mp4");
      const stats = await fs.stat(videoPath);
      const fileSize = stats.size;
      const range = req.headers.range;

      if (range) {
        const parts = range.replace(/bytes=/, "").split("-");
        let start: number;
        let end: number;

        // Handle suffix range (e.g., "bytes=-500" = last 500 bytes)
        if (parts[0] === "") {
          const suffixLength = parseInt(parts[1], 10);
          if (isNaN(suffixLength) || suffixLength <= 0) {
            res.writeHead(416, {
              'Content-Range': `bytes */${fileSize}`,
              'Accept-Ranges': 'bytes',
            });
            res.end();
            return;
          }
          start = Math.max(0, fileSize - suffixLength);
          end = fileSize - 1;
        } else {
          // Handle standard or open-ended range
          start = parseInt(parts[0], 10);
          end = parts[1] ? parseInt(parts[1], 10) : fileSize - 1;
        }

        // Validate range values
        if (isNaN(start) || isNaN(end) || start < 0 || start >= fileSize || end < start) {
          res.writeHead(416, {
            'Content-Range': `bytes */${fileSize}`,
            'Accept-Ranges': 'bytes',
          });
          res.end();
          return;
        }

        // Clamp end to valid bounds
        const clampedEnd = Math.min(end, fileSize - 1);
        const chunksize = (clampedEnd - start) + 1;
        const file = createReadStream(videoPath, { start, end: clampedEnd });
        const head = {
          'Content-Range': `bytes ${start}-${clampedEnd}/${fileSize}`,
          'Accept-Ranges': 'bytes',
          'Content-Length': chunksize,
          'Content-Type': 'video/mp4',
        };

        res.writeHead(206, head);
        file.pipe(res);
      } else {
        const head = {
          'Content-Length': fileSize,
          'Content-Type': 'video/mp4',
          'Accept-Ranges': 'bytes',
        };
        res.writeHead(200, head);
        createReadStream(videoPath).pipe(res);
      }
    } catch (error) {
      res.status(404).json({ error: "Video file not found" });
    }
  });

  const httpServer = createServer(app);

  return httpServer;
}
