# Concrete

Concrete turns building drawings into an interactive workspace. Upload a floor plan, ask the Gemini vision-language model questions about what it shows, and reconstruct a schematic 3D model you can inspect alongside the original.

## Get started

- **Hosted demo.** Open the [Concrete demo](https://agentic.95.133.254.90.sslip.io/). You can browse the saved examples from **Buildings**. To upload, build a model, or ask a question, enter the demo code under **Access code** and select **Unlock workspace** if prompted. The hosted workspace is shared, so use a sample drawing or a file you can share.
- **Local app.** Follow [Run Concrete locally](#run-concrete-locally) to use your own Gemini credentials.
- **Sample floor plan.** Download [cubicasa5k-preview.zip](https://github.com/Programmercloud-cmd/JunctionHack26/releases/download/v0.1.0/cubicasa5k-preview.zip), unzip it, and try `cubicasa5k/colorful-11397.png`. The archive includes all 241 CubiCasa5K PNGs in the Junction preview dataset and their credits in `LICENSE.md`. The images are licensed [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

## Upload an image, build a model, and ask a question

1. **Create a Building.** On **Buildings**, click **New Building**, enter a **Building name**, and click **Create Building**. This opens its overview.
2. **Upload your floor plan.** Click **Upload drawings** and choose a PNG or JPG, or drop it in the upload area. Concrete saves the original and starts interpreting it automatically. When the filename appears under **Drawings**, click it to open the drawing and its chat. You can also start a fresh conversation with **New chat** under **Chats**.
3. **Reconstruct it in 3D.** Select **3D Model** above the drawing, then click **Build model** in the conversation. Follow progress in **Active tasks**. Open the task card and click **Stop task** to end the job. When a model is ready, open **3D Model** to view it, drag to orbit, and scroll to zoom. Open **View settings** to choose a floor or slice the view with **Visible height**.
4. **Ask the VLM about the original.** Type a question in **Message Concrete**, such as “What labeled spaces are shown on this drawing?” and click **Send** or press Enter. Click a citation in the answer to open the referenced region of the original. Expand **Evidence and checks** for the support review, calculations, or missing information when available. You can also ask questions while 3D reconstruction is running.

Use **Building overview** to return to your drawings and saved chats. Each chat has its own history and can use the Building’s shared drawings. Switching the visible drawing keeps the same chat.

## What you can do

- **Inspect drawings.** Upload JPG, PNG, PDF, SVG, or DXF. Add related drawings to one Building, browse the originals with **Drawings**, and use **View settings** to switch pages in a PDF.
- **Ask about the source.** Try visible room labels, counts, or dimensions printed on a plan. The technical answer cites drawing regions or original IFC records when the source supports the answer. Concrete can ask for clarification or identify missing evidence.
- **Explore and export a reconstruction.** Inspect schematic floors, walls, openings, and other features derived from the drawings. Use **Concept** for a styled view or **Files** → **Download IFC** to export the model. To overlay saved geometry on the original, ask Concrete to compare the model with the drawing. Inferred geometry and dimensions can be incomplete, and unknown scale stays unscaled. Use the original drawing to verify details.
- **Open a supplied IFC.** Upload a native IFC as its own Building to explore and ask about its original objects and properties, such as “How many windows are in this IFC model?”
- **Mark up the view.** Open the hammer menu to **Point**, **Draw**, or **Measure** on the drawing or model, then attach a saved mark to a message. Enter measurement values and units where needed. These marks are saved as user input. [Projects and marks](docs/PROJECTS_AND_MARKS.md)
- **Use voice.** Click the microphone to start dictating and click again to stop. Review the transcript before sending. With ElevenLabs configured, enable **Read answers aloud** to hear new replies. [Voice setup](docs/VOICE.md)

## Run Concrete locally

Use a Bash shell with Git, Python 3.12+, and curl. Install system Cairo if you plan to open SVG or DXF files.

```sh
git clone --branch feat/agentic-chat https://github.com/Programmercloud-cmd/JunctionHack26.git
cd JunctionHack26
bash scripts/bootstrap.sh
```

In the repository root, create or edit `.env.local` and set `GEMINI_API_KEY` to your Gemini API key. Keep the key in that local file. If your account uses different model IDs, set the corresponding overrides listed in [`.env.example`](.env.example). Then start the server and open [http://127.0.0.1:8000](http://127.0.0.1:8000).

```sh
bash scripts/dev.sh
```

Restart the server after editing `.env.local`. Uploads, drawing previews, and native IFC viewing work without a key. Automatic interpretation, 3D reconstruction, and answers use server-side Gemini. Drawing requests send source images to Gemini, and native IFC questions can send extracted records. Local originals, models, and chats are saved under `.runtime` by default. Run `.venv/bin/python scripts/doctor.py` to check dependencies and whether credentials are configured.

## Limits and troubleshooting

- Drawings are limited to 10 MiB each, with up to five pages per PDF. Input images over 40 megapixels are rejected. Uncompressed IFC STEP uploads are limited to 25 MiB, 4,000 render-catalog elements, and one million triangles. For DWG, export to a supported format before uploading. [Source formats](docs/SOURCE_FORMATS.md)
- **Build model** can run multiple generation and review rounds. Each round can incur provider usage, and the render job has no total time or cost cap. Use **Stop task** to retain the last usable model and original drawings. [Rendering contract](docs/AGENTIC_CHAT_CONTRACT.md#rendering)
- If Gemini reports an error, check your key and model access. The agentic path has separately configurable models for interpretation, routing, basic and advanced QA, UI actions, reconstruction, and support review. The doctor checks key presence only. [Model settings](.env.example)
- For details on shared Buildings, model fidelity, or deployment, see [Buildings and shared drawings](docs/BUILDINGS_SHARED_DRAWINGS.md), [fidelity results](docs/SCHEMATIC_FIDELITY_RESULTS.md), and [agentic deployment](docs/AGENTIC_DEPLOYMENT.md).

## Development checks

```sh
bash scripts/test.sh
```

To run browser checks with injected providers and Chromium, install the optional browser requirements.

```sh
.venv/bin/python -m pip install -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
RUN_BROWSER_TESTS=1 bash scripts/test.sh tests/test_buildings_shared_browser.py tests/test_agent_e2e_browser.py
```

## Counting benchmark

With the app's Gemini credential configured and the full Junction dataset in `junction-dataset/`, run from the repository root:

```sh
PYTHONPATH=. .venv/bin/python evaluation/counting/benchmark.py
```

The default run samples three PDF and three PNG counting questions and scores exact matches. Add `--type length` or `--type area` to sample six original PDFs of that question type and score answers within 2% of the reference after unit conversion. The dataset has no PNG rows for those two types. IFC area rows are outside this drawing-interpretation workflow.

The benchmark uploads the originals to an isolated app store, waits for interpretation, and runs chat routing and QA. The terminal shows model-call progress, separate upload and question timings, and scores. The run directory printed at startup contains the sample manifest and per-case results.

For the two-call experiment, add `--pipeline interpretation-only`. It samples ten questions per group (PDF count, PNG count, PDF length, and PDF area). Gemini 4 Hydrogen builds a question-independent interpretation from each original drawing, then receives the saved `interpretations.json` and exact question to produce a structured numeric answer. The second call uses the JSON as its evidence. This mode skips chat routing, intent resolution, Gemini Decisions, and answer review. Its run directory includes `results.html` with a combined counting score and per-case results.
