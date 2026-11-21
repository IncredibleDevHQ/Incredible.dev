# Recording with your own camera

The studio records a chapter in the browser, with the marks that say where each line starts. A
camera of your own gives a better picture and sound. Record both at once, and the studio puts
the camera's file under the studio's take by sound, so every line starts where you said it. The
film can then be rendered in 4K from the camera's picture.

## Setting up the camera

The settings below are for a Sony α7 V, checked against Sony's
[Help Guide](https://helpguide.sony.net/ilc/2540/v1/en/). Other cameras have the same choices
under their own names: 30 frames a second, the camera's best 4K, a finished look, and your
microphone into the camera.

| Setting | Choose | Why |
| --- | --- | --- |
| NTSC/PAL Selector (Setup → Area/Date) | NTSC | PAL records 25 or 50 fps, which steps a little in a 30 fps film |
| File Format | XAVC S 4K | the default is XAVC S HD; XAVC HS 4K isn't offered at 30p |
| Movie Setting | 30p, 4:2:2 10-bit, 140 Mbps | about 1 GB a minute, so a 10-minute chapter is about 10.5 GB |
| Picture Profile | PP11 (S-Cinetone) | a finished look that needs no grading |
| Proxy Recording | Off | the studio makes its own copies |
| Audio | your microphone into the camera, 48 kHz | the camera's sound is the film's sound |
| Card | SDXC V60 or faster, or CFexpress Type A | SDHC splits files at 4 GB |

S-Log3 looks flat until it is graded, and the studio doesn't grade it yet: a clip in S-Log3 says
so when it comes in. A clip in HLG is brought down to the film's range.

USB streaming is optional. The α7 V can show its picture to the studio over USB while it records
to the card (Movie Rec During Streaming), but it turns the Picture Profile off while it streams.
Check on your first day that the card's file keeps S-Cinetone. If it doesn't, record the studio's
take with the computer's own camera and microphone instead.

## Recording a chapter

1. Start the camera.
2. Record the chapter in the studio as usual: the reading guide, and Space at each line.
3. Stop the camera once the take has ended.

The camera can roll through several chapters, or through retakes: the studio finds the take it
is matched to wherever it is in the clip.

## Bringing the camera's file in

Put the card in the computer. On the chapter, next to its take, press **Camera file**. The clips
on the card are listed newest first, with when each was recorded, how long it runs and its size,
and the clip recorded at the take's time is picked and marked. Press **Use** (or pick a file
instead, if you copied the clip somewhere first).

The clip is read where it is: there is no upload and no size limit. The chapter, and the bar's
running tasks, say how far it has come: copying it onto the studio's computer, matching its
sound to the take, then making its copies (one in the film's size for the studio and HD films,
one in 4K). A 10-minute chapter takes about as long as it runs. You can go on working meanwhile.

Once it is in, the camera's file is the chapter's take, cut to just the stretch the studio's take
was found in, and the chapter says which take it was matched to. **Undo** puts the studio's take
back. It is refused, and the studio's take stays, when:

- the two recordings don't sound alike (the wrong clip, or the camera's microphone was off);
- they sound alike in more than one place (the clip holds another take of the same lines): pick
  the clip with this take alone, or trim it;
- the camera started after the take began, or stopped during its last line.

**Bring a recording** (the arrow over the frame) brings a clip or a file in without a take to
match: its lines are spread at the plan's pace.

## Where the files go

Every take's recording is kept as it arrived, in `<workspace>/house/footage/<episode>/`. Camera
files are large, so give them a drive of their own with `DESIGN_AGENT_FOOTAGE_DIR` (an external
SSD, say `/Volumes/Footage/creative-house`). The originals are never deleted, not even with their
take: they are yours to keep or clear. With `DESIGN_AGENT_FOOTAGE_BUCKET` they go to S3 (or
MinIO) instead.

The studio reads cards in `/Volumes` on macOS and in `/media`, `/run/media` and `/mnt` on Linux.
Point `DESIGN_AGENT_CAMERA_DIRS` at another folder, for example one you copy cards to.

## Rendering in 4K

Pick **4K** beside Render the film. The film is the same page rendered at twice the density, so
its pictures, type and windows are the same as in 1080p, and each take shows its 4K copy. A take
recorded no taller than 1080 (the browser's own) is scaled up, and the film page says how many
were. A film in 4K takes about 2.3 times as long to render, and its frames take about 2.5 GB of
the render computer's disk for each minute of film while it renders: the render is refused before
it starts when there isn't the room. HDR films aren't made in 4K.
