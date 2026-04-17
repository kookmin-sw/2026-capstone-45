import os
import asyncio

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse

from .font import PathToFontFamily


app = FastAPI(root_path="/api")
font_family = PathToFontFamily()


@app.get("/health")
async def health():
    return {"health": "ok"}


@app.get("/rendered/{doc_id}")
async def rendered_document(doc_id: str):
    path = f"./rendered/{doc_id}.json"
    # if not os.path.exists(path):
    #     raise HTTPException(status_code=404)

    return FileResponse("debug_finish.json")


@app.get("/fonts.css")
async def get_fonts_map():
    css = await asyncio.to_thread(lambda: font_family.build_css())

    return PlainTextResponse(css, media_type="text/css")


@app.get("/font/{filename}")
async def get_font_file(filename: str):
    return FileResponse(f"data/font/{filename}")
