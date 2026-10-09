import os
import re
import json
import uuid
import logging
import aiohttp
from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, File, Form
from routes.auth import get_current_admin, has_permission, require_permission
from database import (
    save_product, get_product, get_product_by_slug, list_products,
    update_product, delete_product, search_products, get_products_by_category,
    get_db_context,
)

logger = logging.getLogger("chiki_webhook")
router = APIRouter(prefix="/catalog", tags=["catalog"])

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 20 * 1024 * 1024


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def _parse_json_list(value: str | None, default: list = None) -> list:
    if not value:
        return default if default is not None else []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else [data]
    except Exception:
        return default if default is not None else []


def _upload_image_to_imghippo(contents: bytes, filename: str = "image") -> str:
    """Upload image bytes to imghippo and return the public URL."""
    imghippo_key = os.environ.get("IMGHIPPO_API_KEY")

    async def _do():
        payload = aiohttp.FormData()
        payload.add_field("api_key", imghippo_key)
        payload.add_field("file", contents, filename=filename)
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.imghippo.com/v1/upload", data=payload) as resp:
                img_data = await resp.json()
                if not resp.ok or not img_data.get("success"):
                    raise HTTPException(
                        status_code=400,
                        detail=img_data.get("message", "Imghippo upload failed"),
                    )
                return img_data["data"]["url"]

    import asyncio
    try:
        loop = asyncio.get_running_loop()
        return loop.run_until_complete(_do())
    except RuntimeError:
        return asyncio.run(_do())


# ── PRODUCTS ─────────────────────────────────────────────────────────────


@router.post("/products/add")
async def add_product(
    name: str = Form(...),
    category: str = Form("general"),
    description: str = Form(""),
    short_description: str = Form(""),
    price: str = Form(""),
    mrp: str = Form(""),
    unit: str = Form("piece"),
    moq: str = Form(""),
    ingredients: str = Form(""),
    sort_order: int = Form(0),
    slug: str = Form(None),
    media_url: str = Form(None, description="Product image URL"),
    media_type: str = Form("image", description="image/video/etc"),
    variants_json: str = Form("[]", description='JSON array of variants [{"label","price","sku"}]'),
    stock_quantity: int = Form(None),
    nutritional_facts: str = Form(None),
    bulk_discount_tiers: str = Form("[]", description='JSON array of bulk discount tiers'),
    is_active: bool = Form(True),
    image: UploadFile = File(None),
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    product_slug = slug or _slugify(name)

    existing = get_product_by_slug(product_slug)
    if existing:
        counter = 1
        while get_product_by_slug(f"{product_slug}-{counter}"):
            counter += 1
        product_slug = f"{product_slug}-{counter}"

    ingredient_list = [t.strip() for t in ingredients.split(",") if t.strip()] if ingredients else []
    variants = _parse_json_list(variants_json)

    # Handle file upload
    final_url = media_url
    final_type = media_type
    if image and image.filename:
        ext = os.path.splitext(image.filename)[1].lower()
        if ext not in ALLOWED_IMAGE_EXT:
            raise HTTPException(status_code=400, detail=f"Image must be one of {ALLOWED_IMAGE_EXT}")
        contents = await image.read()
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File too large. Max: 20MB")
        final_url = _upload_image_to_imghippo(contents, image.filename)
        final_type = "image"

    product_id = save_product(
        name=name,
        slug=product_slug,
        category=category,
        description=description,
        short_description=short_description,
        price=price,
        mrp=mrp,
        unit=unit,
        moq=moq,
        media_url=final_url,
        media_type=final_type,
        ingredients=ingredient_list,
        sort_order=sort_order,
        variants_json=variants,
        stock_quantity=stock_quantity,
        nutritional_facts=nutritional_facts,
        bulk_discount_tiers=_parse_json_list(bulk_discount_tiers),
        actor=current_admin,
    )

    if not is_active:
        update_product(product_id, is_active=False)

    return {"status": "created", "id": product_id, "slug": product_slug}


@router.get("/products/list")
async def list_all_products(
    category: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_admin: dict = Depends(require_permission("view_products")),
):
    items = list_products(category=category, limit=limit)
    return {"count": len(items), "items": items}


@router.get("/products/get/{product_id}")
async def get_product_endpoint(product_id: int, current_admin: dict = Depends(require_permission("view_products"))):
    item = get_product(product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    return item


@router.get("/products/by-slug/{slug}")
async def get_product_by_slug_endpoint(slug: str):
    item = get_product_by_slug(slug)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    return item


@router.get("/products/search")
async def search_products_endpoint(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    current_admin: dict = Depends(require_permission("view_products")),
):
    items = search_products(q, limit=limit)
    return {"count": len(items), "items": items}


@router.get("/products/by-category/{category}")
async def get_by_category(
    category: str,
    limit: int = Query(50, ge=1, le=200),
    current_admin: dict = Depends(require_permission("view_products")),
):
    items = get_products_by_category(category, limit=limit)
    return {"category": category, "count": len(items), "items": items}


@router.put("/products/update/{product_id}")
async def update_product_endpoint(
    product_id: int,
    name: str = Form(None),
    category: str = Form(None),
    description: str = Form(None),
    short_description: str = Form(None),
    price: str = Form(None),
    mrp: str = Form(None),
    unit: str = Form(None),
    moq: str = Form(None),
    ingredients: str = Form(None),
    is_active: bool = Form(None),
    sort_order: int = Form(None),
    media_url: str = Form(None),
    media_type: str = Form(None),
    variants_json: str = Form(None),
    stock_quantity: int = Form(None),
    nutritional_facts: str = Form(None),
    bulk_discount_tiers: str = Form(None),
    image: UploadFile = File(None),
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    item = get_product(product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")

    updates = {}
    if name is not None:
        updates["name"] = name
        updates["slug"] = _slugify(name)
    if category is not None:
        updates["category"] = category
    if description is not None:
        updates["description"] = description
    if short_description is not None:
        updates["short_description"] = short_description
    if price is not None:
        updates["price"] = price
    if mrp is not None:
        updates["mrp"] = mrp
    if unit is not None:
        updates["unit"] = unit
    if moq is not None:
        updates["moq"] = moq
    if ingredients is not None:
        updates["ingredients"] = [t.strip() for t in ingredients.split(",") if t.strip()]
    if is_active is not None:
        updates["is_active"] = 1 if is_active else 0
    if sort_order is not None:
        updates["sort_order"] = sort_order
    if variants_json is not None:
        updates["variants_json"] = _parse_json_list(variants_json)
    if stock_quantity is not None:
        updates["stock_quantity"] = stock_quantity
    if nutritional_facts is not None:
        updates["nutritional_facts"] = nutritional_facts
    if bulk_discount_tiers is not None:
        updates["bulk_discount_tiers"] = _parse_json_list(bulk_discount_tiers)

    if image and image.filename:
        ext = os.path.splitext(image.filename)[1].lower()
        if ext not in ALLOWED_IMAGE_EXT:
            raise HTTPException(status_code=400, detail=f"Image must be one of {ALLOWED_IMAGE_EXT}")
        contents = await image.read()
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File too large. Max: 20MB")
        updates["media_url"] = _upload_image_to_imghippo(contents, image.filename)
        updates["media_type"] = "image"
    elif media_url is not None:
        updates["media_url"] = media_url
        if media_type is not None:
            updates["media_type"] = media_type

    if not updates:
        raise HTTPException(status_code=400, detail="No updatable fields provided")
    update_product(product_id, **updates, actor=current_admin)
    return {"status": "updated", "id": product_id}


@router.delete("/products/delete/{product_id}")
async def delete_product_endpoint(
    product_id: int,
    hard: bool = Query(False),
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    item = get_product(product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    delete_product(product_id, hard=hard, actor=current_admin)
    return {"status": "deleted" if hard else "deactivated", "id": product_id}


@router.get("/products/catalog")
async def get_catalog(
    category: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    items = list_products(category=category, limit=limit)
    return {
        "count": len(items),
        "products": [
            {
                "id": p["id"],
                "name": p["name"],
                "slug": p["slug"],
                "category": p["category"],
                "short_description": p["short_description"],
                "price": p["price"],
                "mrp": p["mrp"],
                "moq": p["moq"],
                "media_url": p.get("media_url"),
                "media_type": p.get("media_type"),
            }
            for p in items
        ],
    }


# ── CATEGORIES ───────────────────────────────────────────────────────────


@router.get("/categories")
async def list_categories(current_admin: dict = Depends(require_permission("view_products"))):
    with get_db_context() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category"
        ).fetchall()
    return {"categories": [r[0] for r in rows if r[0]]}


# ── NEW ARRIVALS (stored in products with category='new_arrival') ────────


@router.post("/new-arrivals/add")
async def add_new_arrival(
    name: str = Form(...),
    description: str = Form(""),
    short_description: str = Form(""),
    price: str = Form(""),
    ingredients: str = Form(""),
    sort_order: int = Form(0),
    slug: str = Form(None),
    media_url: str = Form(None),
    media_type: str = Form("image"),
    image: UploadFile = File(None),
    current_admin: dict = Depends(require_permission("catalogue_new_arrival")),
):
    product_slug = slug or _slugify(name)
    existing = get_product_by_slug(product_slug)
    if existing:
        counter = 1
        while get_product_by_slug(f"{product_slug}-{counter}"):
            counter += 1
        product_slug = f"{product_slug}-{counter}"

    ingredient_list = [t.strip() for t in ingredients.split(",") if t.strip()] if ingredients else []

    final_url = media_url
    final_type = media_type
    if image and image.filename:
        ext = os.path.splitext(image.filename)[1].lower()
        if ext not in ALLOWED_IMAGE_EXT:
            raise HTTPException(status_code=400, detail=f"Image must be one of {ALLOWED_IMAGE_EXT}")
        stored_name = f"{uuid.uuid4().hex}{ext}"
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploaded_files", "products")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, stored_name)
        size = 0
        with open(file_path, "wb") as f:
            while True:
                chunk = await image.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    os.unlink(file_path)
                    raise HTTPException(status_code=413, detail="File too large. Max: 20MB")
                f.write(chunk)
        final_url = f"/uploaded_files/products/{stored_name}"
        final_type = "image"

    product_id = save_product(
        name=name,
        slug=product_slug,
        category="new_arrival",
        description=description,
        short_description=short_description,
        price=price,
        media_url=final_url,
        media_type=final_type,
        ingredients=ingredient_list,
        sort_order=sort_order,
    )
    return {"status": "created", "id": product_id, "slug": product_slug}


@router.get("/new-arrivals/list")
async def list_new_arrivals(
    limit: int = Query(50, ge=1, le=200),
    current_admin: dict = Depends(require_permission("catalogue_new_arrival")),
):
    items = list_products(category="new_arrival", limit=limit)
    return {"count": len(items), "items": items}


@router.delete("/new-arrivals/delete/{product_id}")
async def delete_new_arrival(
    product_id: int,
    hard: bool = Query(True),
    current_admin: dict = Depends(require_permission("catalogue_new_arrival")),
):
    item = get_product(product_id)
    if not item or item.get("category") != "new_arrival":
        raise HTTPException(status_code=404, detail="New arrival not found")
    delete_product(product_id, hard=hard)
    return {"status": "deleted" if hard else "deactivated", "id": product_id}
