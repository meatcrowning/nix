// The userscript manager loads the pinned browser build through @require.
// Keep named imports in our source without embedding the library in the script.
export const {
  Input, BlobSource, MP4, WEBM, MATROSKA, VideoSampleSink,
  Output, BufferTarget, WebMOutputFormat, Mp4OutputFormat, CanvasSource, canEncodeVideo,
} = Mediabunny;
