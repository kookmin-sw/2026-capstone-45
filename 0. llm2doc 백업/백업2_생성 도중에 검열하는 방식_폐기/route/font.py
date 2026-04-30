import asyncio

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse

from llm2doc.font import PathToFontFamily

router = APIRouter(prefix="/fonts")
font_family = PathToFontFamily()


@router.get("/fonts.css")
async def get_fonts_map():
    css = await asyncio.to_thread(lambda: font_family.build_css())

    return PlainTextResponse(css, media_type="text/css")


@router.get("/{filename}")
async def get_font_file(filename: str):
    return FileResponse(f"data/font/{filename}")
