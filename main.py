from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import SessionLocal, User, Article, Comment, Like, SliderItem, PasswordReset, Category, ArticleCategory, Notification, Subscription, Bookmark, Video, VideoLike, VideoComment, VideoBookmark, Complaint
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import os
import shutil
from pathlib import Path
import uuid
import random
import string
import re

def clean_html(text):
    """Удаляет HTML-теги из текста"""
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text)

app = FastAPI(title="StoryBlog - Платформа для историй")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

# Конфиг
SECRET_KEY = "your-secret-key-change-this-12345"
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_notification(db: Session, user_id: int, from_user_id: int, article_id: int, type: str, message: str, link: str = ""):
    if user_id == from_user_id:
        return
    notif = Notification(
        user_id=user_id,
        from_user_id=from_user_id,
        article_id=article_id,
        type=type,
        message=message,
        link=link
    )
    db.add(notif)
    db.commit()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        return user
    except:
        return None

def get_video_or_404(db: Session, video_id: int):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return None
    return video

# ============ ГЛАВНАЯ ============
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, category: str = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    categories = db.query(Category).all()
    
    query = db.query(Article).filter(Article.is_published == True)
    selected_category = None
    if category:
        selected_category = db.query(Category).filter(Category.slug == category).first()
        if selected_category:
            article_ids = db.query(ArticleCategory.article_id).filter(ArticleCategory.category_id == selected_category.id)
            query = query.filter(Article.id.in_(article_ids))
    
    articles = query.order_by(Article.created_at.desc()).limit(20).all()
    
    for article in articles:
        author = db.query(User).filter(User.id == article.user_id).first()
        article.author_name = author.username if author else f"Автор #{article.user_id}"
        article.author_avatar = author.avatar if author else 'default.png'
        article_cat = db.query(ArticleCategory).filter(ArticleCategory.article_id == article.id).first()
        if article_cat:
            cat = db.query(Category).filter(Category.id == article_cat.category_id).first()
            article.category = cat
    
    week_ago = datetime.utcnow() - timedelta(days=7)
    popular_articles = db.query(Article).filter(
        Article.is_published == True,
        Article.created_at >= week_ago
    ).order_by(Article.views.desc()).limit(5).all()
    
    for article in popular_articles:
        author = db.query(User).filter(User.id == article.user_id).first()
        article.author_name = author.username if author else f"Автор #{article.user_id}"
        article.author_avatar = author.avatar if author else 'default.png'
    
    authors_stats = []
    all_users = db.query(User).all()
    for u in all_users:
        articles_count = db.query(Article).filter(Article.user_id == u.id, Article.is_published == True).count()
        if articles_count > 0:
            total_views = db.query(func.sum(Article.views)).filter(Article.user_id == u.id, Article.is_published == True).scalar() or 0
            authors_stats.append({
                "id": u.id,
                "username": u.username,
                "avatar": u.avatar,
                "articles_count": articles_count,
                "total_views": total_views
            })
    
    top_authors = sorted(authors_stats, key=lambda x: x["total_views"], reverse=True)[:5]
    comments = db.query(Comment).all()
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "articles": articles,
        "comments": comments,
        "user": user,
        "slider_items": slider_items,
        "categories": categories,
        "selected_category": selected_category,
        "popular_articles": popular_articles,
        "top_authors": top_authors,
        "meta_title": f"{selected_category.name} - StoryBlog" if selected_category else "StoryBlog - Истории и блоги",
        "meta_description": f"Статьи в категории {selected_category.name}" if selected_category else "Платформа для публикации личных историй"
    })

# ============ РЕГИСТРАЦИЯ И ЛОГИН ============
@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    return templates.TemplateResponse("register.html", {"request": request, "user": user, "slider_items": slider_items})

@app.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter((User.email == email) | (User.username == username)).first()
    if existing_user:
        user = get_current_user(request, db)
        slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
        return templates.TemplateResponse("register.html", {"request": request, "error": "Email или имя уже используются", "user": user, "slider_items": slider_items})
    
    hashed_password = get_password_hash(password)
    new_user = User(email=email, username=username, hashed_password=hashed_password)
    
    if db.query(User).count() == 0:
        new_user.is_admin = True
    
    db.add(new_user)
    db.commit()
    
    access_token = create_access_token(data={"user_id": new_user.id})
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    return templates.TemplateResponse("login.html", {"request": request, "user": user, "slider_items": slider_items})

@app.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        current_user = get_current_user(request, db)
        slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
        return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный email или пароль", "user": current_user, "slider_items": slider_items})
    
    access_token = create_access_token(data={"user_id": user.id})
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("access_token")
    return response

# ============ ПРОФИЛЬ ============
@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    published_articles = db.query(Article).filter(
        Article.user_id == user.id,
        Article.is_published == True
    ).order_by(Article.created_at.desc()).all()
    
    draft_articles = db.query(Article).filter(
        Article.user_id == user.id,
        Article.is_published == False
    ).order_by(Article.created_at.desc()).all()
    user_videos = db.query(Video).filter(Video.user_id == user.id).order_by(Video.created_at.desc()).all()
    
    subscribers_count = db.query(Subscription).filter(Subscription.author_id == user.id).count()
    subscriptions_count = db.query(Subscription).filter(Subscription.subscriber_id == user.id).count()
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "published_articles": published_articles,
        "draft_articles": draft_articles,
        "user_videos": user_videos, 
        "subscribers_count": subscribers_count,
        "subscriptions_count": subscriptions_count,
        "slider_items": slider_items
    })

@app.post("/profile/edit")
async def edit_profile(
    request: Request,
    username: str = Form(...),
    avatar: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    user.username = username
    
    if avatar and avatar.filename:
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if avatar.content_type not in allowed_types:
            slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
            return templates.TemplateResponse("profile.html", {
                "request": request,
                "user": user,
                "error": "Можно загружать только JPEG, PNG, GIF или WEBP",
                "slider_items": slider_items
            })
        
        os.makedirs("static/avatars", exist_ok=True)
        file_extension = Path(avatar.filename).suffix.lower()
        filename = f"{uuid.uuid4().hex}{file_extension}"
        file_path = f"static/avatars/{filename}"
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(avatar.file, buffer)
        
        if user.avatar and user.avatar != 'default.png':
            old_path = f"static/avatars/{user.avatar}"
            if os.path.exists(old_path):
                os.remove(old_path)
        
        user.avatar = filename
    
    db.commit()
    return RedirectResponse(url="/profile", status_code=303)

# ============ СОЗДАНИЕ И РЕДАКТИРОВАНИЕ СТАТЕЙ ============
@app.get("/create", response_class=HTMLResponse)
async def create_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    categories = db.query(Category).all()
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    return templates.TemplateResponse("create.html", {"request": request, "user": user, "categories": categories, "slider_items": slider_items})

@app.post("/create")
async def create_article(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    category_id: int = Form(...),
    is_published: bool = Form(False),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    slug = title.lower().replace(" ", "-")[:50] + f"-{uuid.uuid4().hex[:6]}"
    
    clean_content = clean_html(content)
    # Убираем заголовок из начала описания, если он там есть
    if clean_content.startswith(title):
        clean_content = clean_content[len(title):].strip()
    description = clean_content[:150].strip()
    
    new_article = Article(
        title=title,
        slug=slug,
        description=description,
        content=content,
        user_id=user.id,
        is_published=is_published
    )
    
    db.add(new_article)
    db.commit()
    db.refresh(new_article)
    
    article_cat = ArticleCategory(article_id=new_article.id, category_id=category_id)
    db.add(article_cat)
    db.commit()
    
    return RedirectResponse(url="/profile", status_code=303)

@app.get("/edit/{article_id}", response_class=HTMLResponse)
async def edit_article_page(request: Request, article_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article or article.user_id != user.id:
        return RedirectResponse(url="/profile", status_code=303)
    
    categories = db.query(Category).all()
    article_cat = db.query(ArticleCategory).filter(ArticleCategory.article_id == article_id).first()
    current_category_id = article_cat.category_id if article_cat else None
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("edit_article.html", {
        "request": request,
        "user": user,
        "article": article,
        "categories": categories,
        "current_category_id": current_category_id,
        "slider_items": slider_items
    })

@app.post("/edit/{article_id}")
async def edit_article(
    request: Request,
    article_id: int,
    title: str = Form(...),
    content: str = Form(...),
    category_id: int = Form(...),
    is_published: bool = Form(False),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article or article.user_id != user.id:
        return RedirectResponse(url="/profile", status_code=303)
    
    article.title = title
    article.content = content
    article.is_published = is_published
    
    clean_content = clean_html(content)
    if clean_content.startswith(title):
        clean_content = clean_content[len(title):].strip()
    article.description = clean_content[:150].strip()
    
    article.updated_at = datetime.utcnow()
    
    new_slug = title.lower().replace(" ", "-")[:50] + f"-{uuid.uuid4().hex[:6]}"
    article.slug = new_slug
    
    article_cat = db.query(ArticleCategory).filter(ArticleCategory.article_id == article_id).first()
    if article_cat:
        article_cat.category_id = category_id
    else:
        article_cat = ArticleCategory(article_id=article_id, category_id=category_id)
        db.add(article_cat)
    
    db.commit()
    return RedirectResponse(url="/profile", status_code=303)

@app.post("/delete/{article_id}")
async def delete_article(request: Request, article_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article or article.user_id != user.id:
        return RedirectResponse(url="/profile", status_code=303)
    
    db.query(Comment).filter(Comment.article_id == article_id).delete()
    db.query(Like).filter(Like.article_id == article_id).delete()
    db.delete(article)
    db.commit()
    
    return RedirectResponse(url="/profile", status_code=303)

# ============ СТРАНИЦА СТАТЬИ ============
@app.get("/article/{slug}", response_class=HTMLResponse)
async def article_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.slug == slug).first()
    user = get_current_user(request, db)
    
    if not article or (not article.is_published and (not user or user.id != article.user_id)):
        return templates.TemplateResponse("404.html", {"request": request, "user": user}, status_code=404)
    
    article.views += 1
    db.commit()
    
    author = db.query(User).filter(User.id == article.user_id).first()
    article.author_name = author.username if author else f"Автор #{article.user_id}"
    article.author_avatar = author.avatar if author else 'default.png'
    article.content_html = article.content
    
    article_cat = db.query(ArticleCategory).filter(ArticleCategory.article_id == article.id).first()
    if article_cat:
        cat = db.query(Category).filter(Category.id == article_cat.category_id).first()
        article.category = cat
    
    comments = db.query(Comment).filter(Comment.article_id == article.id).order_by(Comment.created_at.desc()).all()
    for comment in comments:
        comment_author = db.query(User).filter(User.id == comment.user_id).first()
        comment.author_name = comment_author.username if comment_author else f"Пользователь #{comment.user_id}"
    
    user_liked = False
    if user:
        user_liked = db.query(Like).filter(Like.article_id == article.id, Like.user_id == user.id).first() is not None
    
    all_articles = db.query(Article).filter(Article.is_published == True).all()
    total_articles = len(all_articles)
    total_views = sum(a.views for a in all_articles)
    total_likes = sum(a.likes for a in all_articles)
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("article.html", {
        "request": request,
        "article": article,
        "comments": comments,
        "user": user,
        "user_liked": user_liked,
        "total_articles": total_articles,
        "total_views": total_views,
        "total_likes": total_likes,
        "slider_items": slider_items,
        "meta_title": article.title,
        "meta_description": article.description
    })

# ============ ЛАЙКИ И КОММЕНТАРИИ ============
@app.post("/like/{article_id}")
async def like_article(article_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    existing_like = db.query(Like).filter(Like.article_id == article_id, Like.user_id == user.id).first()
    article = db.query(Article).filter(Article.id == article_id).first()
    
    if existing_like:
        db.delete(existing_like)
        article.likes -= 1
    else:
        new_like = Like(article_id=article_id, user_id=user.id)
        db.add(new_like)
        article.likes += 1
        create_notification(
            db=db,
            user_id=article.user_id,
            from_user_id=user.id,
            article_id=article_id,
            type="like",
            message=f"{user.username} лайкнул вашу статью «{article.title[:30]}»",
            link=f"/article/{article.slug}"
        )
    
    db.commit()
    return RedirectResponse(url=f"/article/{article.slug}", status_code=303)

@app.post("/comment/{article_id}")
async def add_comment(
    article_id: int,
    request: Request,
    text: str = Form(...),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        return RedirectResponse(url="/", status_code=303)
    
    new_comment = Comment(article_id=article_id, user_id=user.id, text=text)
    db.add(new_comment)
    db.commit()
    
    create_notification(
        db=db,
        user_id=article.user_id,
        from_user_id=user.id,
        article_id=article_id,
        type="comment",
        message=f"{user.username} оставил комментарий к вашей статье «{article.title[:30]}»",
        link=f"/article/{article.slug}"
    )
    
    mention_pattern = r'@([a-zA-Z0-9_а-яА-Я]+)'
    mentions = re.findall(mention_pattern, text)
    
    for username in mentions:
        mentioned_user = db.query(User).filter(User.username == username).first()
        if mentioned_user and mentioned_user.id != user.id and mentioned_user.id != article.user_id:
            create_notification(
                db=db,
                user_id=mentioned_user.id,
                from_user_id=user.id,
                article_id=article_id,
                type="mention",
                message=f"{user.username} упомянул вас в комментарии к статье «{article.title[:30]}»",
                link=f"/article/{article.slug}#comment-{new_comment.id}"
            )
    
    return RedirectResponse(url=f"/article/{article.slug}#comment-{new_comment.id}", status_code=303)

@app.post("/comment/delete/{comment_id}")
async def delete_comment(comment_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return {"success": False, "error": "Не авторизован"}
    
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        return {"success": False, "error": "Комментарий не найден"}
    
    if comment.user_id != user.id:
        return {"success": False, "error": "Вы можете удалять только свои комментарии"}
    
    db.delete(comment)
    db.commit()
    return {"success": True}

# ============ АДМИН-ПАНЕЛЬ ============
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    pending_articles = db.query(Article).filter(Article.is_published == False).all()
    all_articles = db.query(Article).all()
    all_users = db.query(User).all()
    all_comments = db.query(Comment).all()
    categories = db.query(Category).all()
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    # ========== ЗАГРУЗКА ЖАЛОБ ==========
    complaints = db.query(Complaint).order_by(Complaint.created_at.desc()).all()
    for c in complaints:
        c.user_name = db.query(User).filter(User.id == c.user_id).first().username
        if c.content_type == "article":
            article = db.query(Article).filter(Article.id == c.content_id).first()
            c.content_title = article.title if article else "[Удалено]"
            c.content_url = f"/article/{article.slug}" if article else "#"
        else:
            video = db.query(Video).filter(Video.id == c.content_id).first()
            c.content_title = video.title if video else "[Удалено]"
            c.content_url = f"/video/{c.content_id}" if video else "#"
    # ===================================
    
    # ... остальной код (for article in all_articles, etc.) ...
    
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "pending_articles": pending_articles,
        "all_articles": all_articles,
        "all_users": all_users,
        "all_comments": all_comments,
        "categories": categories,
        "slider_items": slider_items,
        "complaints": complaints,  # ← ДОБАВИТЬ
    })

@app.post("/admin/approve/{article_id}")
async def approve_article(article_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    article = db.query(Article).filter(Article.id == article_id).first()
    if article:
        article.is_published = True
        db.commit()
    
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/delete/{article_id}")
async def admin_delete_article(article_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    article = db.query(Article).filter(Article.id == article_id).first()
    if article:
        db.delete(article)
        db.commit()
    
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/toggle-admin/{user_id}")
async def toggle_admin(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin_user = get_current_user(request, db)
    if not admin_user or not admin_user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.id != admin_user.id:
        user.is_admin = not user.is_admin
        db.commit()
    
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/delete-user/{user_id}")
async def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin_user = get_current_user(request, db)
    if not admin_user or not admin_user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.id != admin_user.id:
        db.query(Comment).filter(Comment.user_id == user_id).delete()
        db.query(Like).filter(Like.user_id == user_id).delete()
        db.query(Article).filter(Article.user_id == user_id).delete()
        db.query(Subscription).filter((Subscription.subscriber_id == user_id) | (Subscription.author_id == user_id)).delete()
        db.query(Bookmark).filter(Bookmark.user_id == user_id).delete()
        db.query(Notification).filter(Notification.user_id == user_id).delete()
        db.delete(user)
        db.commit()
    
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/add-category")
async def add_category(request: Request, name: str = Form(...), icon: str = Form("📁"), db: Session = Depends(get_db)):
    admin_user = get_current_user(request, db)
    if not admin_user or not admin_user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    slug = name.lower().replace(" ", "-").replace("ё", "е")
    existing = db.query(Category).filter(Category.slug == slug).first()
    if existing:
        slug = f"{slug}-{uuid.uuid4().hex[:4]}"
    
    new_cat = Category(name=name, slug=slug, icon=icon)
    db.add(new_cat)
    db.commit()
    
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/delete-category/{cat_id}")
async def delete_category(cat_id: int, request: Request, db: Session = Depends(get_db)):
    admin_user = get_current_user(request, db)
    if not admin_user or not admin_user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    db.query(ArticleCategory).filter(ArticleCategory.category_id == cat_id).delete()
    db.query(Category).filter(Category.id == cat_id).delete()
    db.commit()
    
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/delete-comment/{comment_id}")
async def admin_delete_comment(comment_id: int, request: Request, db: Session = Depends(get_db)):
    admin_user = get_current_user(request, db)
    if not admin_user or not admin_user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    db.query(Comment).filter(Comment.id == comment_id).delete()
    db.commit()
    
    return RedirectResponse(url="/admin", status_code=303)

    # ============ УПРАВЛЕНИЕ ЖАЛОБАМИ ============
@app.post("/admin/complaint/{complaint_id}/resolve")
async def resolve_complaint(complaint_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint:
        complaint.status = "resolved"
        db.commit()
    
    return RedirectResponse(url="/admin#complaints", status_code=303)

@app.post("/admin/complaint/{complaint_id}/dismiss")
async def dismiss_complaint(complaint_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint:
        complaint.status = "dismissed"
        db.commit()
    
    return RedirectResponse(url="/admin#complaints", status_code=303)

@app.post("/admin/complaint/{complaint_id}/delete")
async def delete_complaint(complaint_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint:
        db.delete(complaint)
        db.commit()
    
    return RedirectResponse(url="/admin#complaints", status_code=303)

# ============ УПРАВЛЕНИЕ СЛАЙДЕРОМ ============
@app.get("/admin/slider", response_class=HTMLResponse)
async def admin_slider(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    slider_items = db.query(SliderItem).order_by(SliderItem.order).all()
    return templates.TemplateResponse("admin_slider.html", {"request": request, "user": user, "slider_items": slider_items})

@app.post("/admin/slider/add")
async def add_slider_item(
    request: Request,
    title: str = Form(""),
    label: str = Form(""),
    icon: str = Form("📖"),
    link: str = Form(""),
    image_position: str = Form("cover"),
    text_position: str = Form("center"),
    text_color: str = Form("#ffffff"),
    text_size: str = Form("medium"),
    overlay_opacity: int = Form(30),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    form = await request.form()
    image_file = form.get("image")
    image_url = ""
    
    if image_file and image_file.filename:
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if image_file.content_type in allowed_types:
            os.makedirs("static/uploads", exist_ok=True)
            ext = Path(image_file.filename).suffix.lower()
            filename = f"slider_{uuid.uuid4().hex}{ext}"
            file_path = f"static/uploads/{filename}"
            
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(image_file.file, buffer)
            
            image_url = f"/static/uploads/{filename}"
    
    max_order = db.query(SliderItem).count()
    new_item = SliderItem(
        title=title if title else "",
        label=label if label else "",
        icon=icon,
        image_url=image_url,
        link=link,
        image_position=image_position,
        text_position=text_position,
        text_color=text_color,
        text_size=text_size,
        overlay_opacity=overlay_opacity,
        order=max_order
    )
    db.add(new_item)
    db.commit()
    
    return RedirectResponse(url="/admin/slider", status_code=303)

@app.post("/admin/slider/edit/{item_id}")
async def edit_slider_item(
    item_id: int,
    request: Request,
    title: str = Form(""),
    label: str = Form(""),
    icon: str = Form("📖"),
    link: str = Form(""),
    is_active: bool = Form(True),
    image_position: str = Form("cover"),
    text_position: str = Form("center"),
    text_color: str = Form("#ffffff"),
    text_size: str = Form("medium"),
    overlay_opacity: int = Form(30),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    item = db.query(SliderItem).filter(SliderItem.id == item_id).first()
    if item:
        item.title = title
        item.label = label
        item.icon = icon
        item.link = link
        item.is_active = is_active
        item.image_position = image_position
        item.text_position = text_position
        item.text_color = text_color
        item.text_size = text_size
        item.overlay_opacity = overlay_opacity
        
        form = await request.form()
        image_file = form.get("image")
        if image_file and image_file.filename:
            allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
            if image_file.content_type in allowed_types:
                os.makedirs("static/uploads", exist_ok=True)
                ext = Path(image_file.filename).suffix.lower()
                filename = f"slider_{uuid.uuid4().hex}{ext}"
                file_path = f"static/uploads/{filename}"
                
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(image_file.file, buffer)
                
                item.image_url = f"/static/uploads/{filename}"
        
        db.commit()
    
    return RedirectResponse(url="/admin/slider", status_code=303)

@app.post("/admin/slider/delete/{item_id}")
async def delete_slider_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    print(f"\n=== УДАЛЕНИЕ СЛАЙДА {item_id} ===")
    
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        print("❌ Нет прав админа")
        return RedirectResponse(url="/", status_code=303)
    
    print(f"✅ Пользователь {user.username} (админ)")
    
    item = db.query(SliderItem).filter(SliderItem.id == item_id).first()
    if item:
        print(f"✅ Слайд найден: {item.title}")
        db.delete(item)
        db.commit()
        print(f"🗑️ Слайд {item_id} УДАЛЁН!")
    else:
        print(f"❌ Слайд с ID {item_id} НЕ НАЙДЕН в базе!")
    
    return RedirectResponse(url="/admin/slider", status_code=303)

@app.post("/admin/slider/reorder")
async def reorder_slider(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/", status_code=303)
    
    form_data = await request.form()
    for key, value in form_data.items():
        if key.startswith('order_'):
            item_id = int(key.split('_')[1])
            item = db.query(SliderItem).filter(SliderItem.id == item_id).first()
            if item:
                item.order = int(value)
    
    db.commit()
    return RedirectResponse(url="/admin/slider", status_code=303)

# ============ ВОССТАНОВЛЕНИЕ ПАРОЛЯ ============
@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request, db: Session = Depends(get_db)):
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    return templates.TemplateResponse("forgot_password.html", {"request": request, "slider_items": slider_items})

@app.post("/forgot-password")
async def forgot_password(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    if not user:
        return templates.TemplateResponse("forgot_password.html", {
            "request": request,
            "message": "Если такой email существует, код сброса отправлен",
            "slider_items": slider_items
        })
    
    code = ''.join(random.choices(string.digits, k=6))
    reset = PasswordReset(user_id=user.id, code=code, expires_at=datetime.utcnow() + timedelta(hours=1))
    db.add(reset)
    db.commit()
    
    print(f"\n=== КОД СБРОСА ПАРОЛЯ ДЛЯ {email} ===\nКОД: {code}\n================================\n")
    
    return templates.TemplateResponse("forgot_password.html", {
        "request": request,
        "message": f"Код сброса отправлен на {email} (проверьте консоль)",
        "slider_items": slider_items
    })

@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, db: Session = Depends(get_db)):
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    return templates.TemplateResponse("reset_password.html", {"request": request, "slider_items": slider_items})

@app.post("/reset-password")
async def reset_password(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    if new_password != confirm_password:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "error": "Пароли не совпадают",
            "email": email,
            "code": code,
            "slider_items": slider_items
        })
    
    if len(new_password) < 4:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "error": "Пароль должен быть не менее 4 символов",
            "email": email,
            "code": code,
            "slider_items": slider_items
        })
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "error": "Пользователь не найден",
            "slider_items": slider_items
        })
    
    reset = db.query(PasswordReset).filter(
        PasswordReset.user_id == user.id,
        PasswordReset.code == code,
        PasswordReset.used == False,
        PasswordReset.expires_at > datetime.utcnow()
    ).first()
    
    if not reset:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "error": "Неверный или истекший код",
            "slider_items": slider_items
        })
    
    user.hashed_password = get_password_hash(new_password)
    reset.used = True
    db.commit()
    
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "success": "Пароль успешно изменен! Теперь вы можете войти",
        "slider_items": slider_items
    })

# ============ ПОИСК ============
@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = "", db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    results = []
    search_query = q.strip()
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    if search_query:
        results = db.query(Article).filter(
            Article.is_published == True,
            (Article.title.ilike(f"%{search_query}%") | 
             Article.content.ilike(f"%{search_query}%") |
             Article.description.ilike(f"%{search_query}%"))
        ).order_by(Article.created_at.desc()).all()
        
        for article in results:
            author = db.query(User).filter(User.id == article.user_id).first()
            article.author_name = author.username if author else f"Автор #{article.user_id}"
    
    return templates.TemplateResponse("search.html", {
        "request": request,
        "user": user,
        "results": results,
        "search_query": search_query,
        "results_count": len(results),
        "slider_items": slider_items,
        "meta_title": f"Поиск: {search_query}" if search_query else "Поиск",
        "meta_description": "Поиск статей на сайте"
    })

# ============ УВЕДОМЛЕНИЯ ============
@app.get("/notifications")
async def get_notifications(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    notifications = db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50).all()
    unread_count = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("notifications.html", {
        "request": request,
        "user": user,
        "notifications": notifications,
        "unread_count": unread_count,
        "slider_items": slider_items
    })

@app.post("/notifications/read/{notif_id}")
async def mark_notification_read(notif_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    notif = db.query(Notification).filter(Notification.id == notif_id, Notification.user_id == user.id).first()
    if notif:
        notif.is_read = True
        db.commit()
    
    return RedirectResponse(url="/notifications", status_code=303)

@app.post("/notifications/mark-all-read")
async def mark_all_read(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).update({"is_read": True})
    db.commit()
    
    return RedirectResponse(url="/notifications", status_code=303)

@app.get("/api/notifications/count")
async def get_notifications_count(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return {"count": 0}
    
    count = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()
    return {"count": count}

@app.get("/api/notifications/list")
async def get_notifications_list(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return {"notifications": []}
    
    notifications = db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(30).all()
    result = []
    
    for n in notifications:
        delta = datetime.utcnow() - n.created_at
        if delta.days > 0:
            time_ago = f"{delta.days} дн. назад"
        elif delta.seconds > 3600:
            time_ago = f"{delta.seconds // 3600} ч. назад"
        elif delta.seconds > 60:
            time_ago = f"{delta.seconds // 60} мин. назад"
        else:
            time_ago = "только что"
        
        notif_type = n.type if n.type else 'default'
        
        if notif_type == 'comment':
            icon_class = 'comment'
        elif notif_type == 'like':
            icon_class = 'like'
        elif notif_type == 'subscribe':
            icon_class = 'subscribe'
        elif notif_type == 'mention':
            icon_class = 'mention'
        elif notif_type == 'video_like':
            icon_class = 'like'
        elif notif_type == 'video_comment':
            icon_class = 'comment'
        else:
            icon_class = 'default'
        
        result.append({
            "id": n.id,
            "type": notif_type,
            "icon_class": icon_class,
            "message": n.message,
            "link": n.link,
            "is_read": n.is_read,
            "time_ago": time_ago
        })
    
    return {"notifications": result}

@app.post("/api/notifications/read/{notif_id}")
async def mark_notification_read_api(notif_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return {"error": "Unauthorized"}
    
    notif = db.query(Notification).filter(Notification.id == notif_id, Notification.user_id == user.id).first()
    if notif:
        notif.is_read = True
        db.commit()
    
    return {"success": True}

@app.post("/api/notifications/mark-all-read")
async def api_mark_all_read(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return {"error": "Unauthorized"}
    
    db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).update({"is_read": True})
    db.commit()
    
    return {"success": True}

# ============ ПОДПИСКИ ============
@app.post("/subscribe/{author_id}")
async def subscribe(author_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    if user.id == author_id:
        return RedirectResponse(url=f"/user/{author_id}", status_code=303)
    
    existing = db.query(Subscription).filter(
        Subscription.subscriber_id == user.id,
        Subscription.author_id == author_id
    ).first()
    
    if existing:
        db.delete(existing)
        db.commit()
    else:
        new_sub = Subscription(subscriber_id=user.id, author_id=author_id)
        db.add(new_sub)
        db.commit()
        
        author = db.query(User).filter(User.id == author_id).first()
        if author:
            create_notification(
                db=db,
                user_id=author_id,
                from_user_id=user.id,
                article_id=None,
                type="subscribe",
                message=f"{user.username} подписался на ваши обновления",
                link=f"/user/{user.id}"
            )
    
    return RedirectResponse(url=f"/user/{author_id}", status_code=303)

@app.get("/user/{user_id}", response_class=HTMLResponse)
async def user_profile(request: Request, user_id: int, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    author = db.query(User).filter(User.id == user_id).first()
    
    if not author:
        return templates.TemplateResponse("404.html", {"request": request, "user": current_user}, status_code=404)
    
    articles = db.query(Article).filter(Article.user_id == user_id, Article.is_published == True).order_by(Article.created_at.desc()).all()
    
    for article in articles:
        article_cat = db.query(ArticleCategory).filter(ArticleCategory.article_id == article.id).first()
        if article_cat:
            cat = db.query(Category).filter(Category.id == article_cat.category_id).first()
            article.category = cat
    
    is_subscribed = False
    subscribers_count = db.query(Subscription).filter(Subscription.author_id == user_id).count()
    
    if current_user:
        is_subscribed = db.query(Subscription).filter(
            Subscription.subscriber_id == current_user.id,
            Subscription.author_id == user_id
        ).first() is not None
    
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("user_profile.html", {
        "request": request,
        "user": current_user,
        "author": author,
        "articles": articles,
        "is_subscribed": is_subscribed,
        "subscribers_count": subscribers_count,
        "slider_items": slider_items,
        "meta_title": f"{author.username} — статьи и публикации",
        "meta_description": f"Все статьи автора {author.username}"
    })

@app.get("/my-subscriptions", response_class=HTMLResponse)
async def my_subscriptions(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    subscriptions = db.query(Subscription).filter(Subscription.subscriber_id == user.id).all()
    authors = []
    
    for sub in subscriptions:
        author = db.query(User).filter(User.id == sub.author_id).first()
        if author:
            articles_count = db.query(Article).filter(Article.user_id == author.id, Article.is_published == True).count()
            author.articles_count = articles_count
            authors.append(author)
    
    if authors:
        author_ids = [a.id for a in authors]
        feed_articles = db.query(Article).filter(
            Article.user_id.in_(author_ids),
            Article.is_published == True
        ).order_by(Article.created_at.desc()).limit(50).all()
        
        for article in feed_articles:
            article_author = db.query(User).filter(User.id == article.user_id).first()
            article.author_name = article_author.username if article_author else f"Автор #{article.user_id}"
            article_cat = db.query(ArticleCategory).filter(ArticleCategory.article_id == article.id).first()
            if article_cat:
                cat = db.query(Category).filter(Category.id == article_cat.category_id).first()
                article.category = cat
    else:
        feed_articles = []
    
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("my_subscriptions.html", {
        "request": request,
        "user": user,
        "authors": authors,
        "feed_articles": feed_articles,
        "slider_items": slider_items
    })

@app.get("/my-subscriptions/authors", response_class=HTMLResponse)
async def my_subscriptions_authors(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    subscriptions = db.query(Subscription).filter(Subscription.subscriber_id == user.id).all()
    authors = []
    
    for sub in subscriptions:
        author = db.query(User).filter(User.id == sub.author_id).first()
        if author:
            articles_count = db.query(Article).filter(Article.user_id == author.id, Article.is_published == True).count()
            author.articles_count = articles_count
            authors.append(author)
    
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("my_subscriptions_authors.html", {
        "request": request,
        "user": user,
        "authors": authors,
        "slider_items": slider_items
    })

# ============ ЗАКЛАДКИ ============
@app.post("/bookmark/{article_id}")
async def toggle_bookmark(article_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    existing = db.query(Bookmark).filter(Bookmark.user_id == user.id, Bookmark.article_id == article_id).first()
    
    if existing:
        db.delete(existing)
        db.commit()
    else:
        new_bookmark = Bookmark(user_id=user.id, article_id=article_id)
        db.add(new_bookmark)
        db.commit()
    
    article = db.query(Article).filter(Article.id == article_id).first()
    if article:
        return RedirectResponse(url=f"/article/{article.slug}", status_code=303)
    return RedirectResponse(url="/", status_code=303)

@app.get("/my-bookmarks", response_class=HTMLResponse)
async def my_bookmarks(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Закладки статей
    bookmarks = db.query(Bookmark).filter(Bookmark.user_id == user.id).order_by(Bookmark.created_at.desc()).all()
    articles = []
    
    for bookmark in bookmarks:
        article = db.query(Article).filter(Article.id == bookmark.article_id, Article.is_published == True).first()
        if article:
            author = db.query(User).filter(User.id == article.user_id).first()
            article.author_name = author.username if author else f"Автор #{article.user_id}"
            article_cat = db.query(ArticleCategory).filter(ArticleCategory.article_id == article.id).first()
            if article_cat:
                cat = db.query(Category).filter(Category.id == article_cat.category_id).first()
                article.category = cat
            article.bookmarked_at = bookmark.created_at
            article.item_type = "article"
            articles.append(article)
    
    # Закладки видео
    video_bookmarks = db.query(VideoBookmark).filter(VideoBookmark.user_id == user.id).order_by(VideoBookmark.created_at.desc()).all()
    videos = []
    
    for vbm in video_bookmarks:
        video = db.query(Video).filter(Video.id == vbm.video_id, Video.is_published == True).first()
        if video:
            author = db.query(User).filter(User.id == video.user_id).first()
            video.author_name = author.username if author else f"Автор #{video.user_id}"
            video.author_avatar = author.avatar if author else 'default.png'
            video.bookmarked_at = vbm.created_at
            video.item_type = "video"
            videos.append(video)
    
    # Объединяем и сортируем по дате добавления
    all_items = articles + videos
    all_items.sort(key=lambda x: x.bookmarked_at, reverse=True)
    
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("my_bookmarks.html", {
        "request": request,
        "user": user,
        "items": all_items,
        "articles_count": len(articles),
        "videos_count": len(videos),
        "slider_items": slider_items
    })

# ============ НАСТРОЙКИ ============
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "user": user,
        "slider_items": slider_items
    })

@app.post("/settings/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    if not verify_password(current_password, user.hashed_password):
        return templates.TemplateResponse("settings.html", {
            "request": request,
            "user": user,
            "error": "Неверный текущий пароль",
            "slider_items": slider_items
        })
    
    if len(new_password) < 4:
        return templates.TemplateResponse("settings.html", {
            "request": request,
            "user": user,
            "error": "Новый пароль должен быть не менее 4 символов",
            "slider_items": slider_items
        })
    
    if new_password != confirm_password:
        return templates.TemplateResponse("settings.html", {
            "request": request,
            "user": user,
            "error": "Новый пароль и подтверждение не совпадают",
            "slider_items": slider_items
        })
    
    user.hashed_password = get_password_hash(new_password)
    db.commit()
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "user": user,
        "message": "Пароль успешно изменен!",
        "slider_items": slider_items
    })

# ============ СТАТИЧЕСКИЕ СТРАНИЦЫ ============
@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    return templates.TemplateResponse("about.html", {
        "request": request,
        "user": user,
        "slider_items": slider_items,
        "meta_title": "О сайте - StoryBlog",
        "meta_description": "Узнайте больше о платформе StoryBlog"
    })

@app.get("/contacts", response_class=HTMLResponse)
async def contacts_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    return templates.TemplateResponse("contacts.html", {
        "request": request,
        "user": user,
        "slider_items": slider_items,
        "meta_title": "Контакты - StoryBlog",
        "meta_description": "Свяжитесь с нами"
    })

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    return templates.TemplateResponse("privacy.html", {
        "request": request,
        "user": user,
        "slider_items": slider_items,
        "meta_title": "Политика конфиденциальности - StoryBlog",
        "meta_description": "Правила обработки персональных данных"
    })

# ============ API ============
@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    all_articles = db.query(Article).filter(Article.is_published == True).all()
    total_articles = len(all_articles)
    total_views = sum(a.views for a in all_articles)
    total_likes = sum(a.likes for a in all_articles)
    
    return {
        "total_articles": total_articles,
        "total_views": total_views,
        "total_likes": total_likes
    }

@app.get("/api/users/search")
async def search_users(q: str = "", db: Session = Depends(get_db)):
    if len(q) < 1:
        return {"users": []}
    
    users = db.query(User).filter(User.username.ilike(f"%{q}%")).limit(10).all()
    return {"users": [{"username": u.username, "email": u.email} for u in users]}

@app.get("/api/feed")
async def api_feed(request: Request, type: str = "fresh", category: str = None, offset: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    
    # ========== ОБРАБОТКА ВИДЕО ==========
    if type == "videos":
        query = db.query(Video).filter(Video.is_published == True)
        query = query.order_by(Video.created_at.desc())
        
        total_count = query.count()
        videos = query.offset(offset).limit(limit).all()
        
        result = []
        for video in videos:
            author = db.query(User).filter(User.id == video.user_id).first()
            
            result.append({
                "id": video.id,
                "title": video.title,
                "slug": str(video.id),
                "description": video.description or "",
                "views": video.views,
                "likes": video.likes,
                "created_at": video.created_at.isoformat(),
                "user_id": video.user_id,
                "author_name": author.username if author else f"Автор #{video.user_id}",
                "author_avatar": author.avatar if author else 'default.png',
                "video_url": video.video_url,
                "thumbnail_url": video.thumbnail_url if hasattr(video, 'thumbnail_url') else None,
                "type": "video",
                "category": None
            })
        
        return {"videos": result, "total": total_count, "has_more": offset + limit < total_count}
    
    # ========== ОБРАБОТКА СТАТЕЙ ==========
    query = db.query(Article).filter(Article.is_published == True)
    
    if category:
        selected_category = db.query(Category).filter(Category.slug == category).first()
        if selected_category:
            article_ids = db.query(ArticleCategory.article_id).filter(ArticleCategory.category_id == selected_category.id)
            query = query.filter(Article.id.in_(article_ids))
    
    if type == "popular":
        query = query.order_by(Article.views.desc())
    elif type == "myfeed" and user:
        subscriptions = db.query(Subscription).filter(Subscription.subscriber_id == user.id).all()
        author_ids = [s.author_id for s in subscriptions]
        if author_ids:
            query = query.filter(Article.user_id.in_(author_ids))
        query = query.order_by(Article.created_at.desc())
    else:
        query = query.order_by(Article.created_at.desc())
    
    total_count = query.count()
    articles = query.offset(offset).limit(limit).all()
    
    result = []
    for article in articles:
        author = db.query(User).filter(User.id == article.user_id).first()
        article_cat = db.query(ArticleCategory).filter(ArticleCategory.article_id == article.id).first()
        category_obj = None
        if article_cat:
            cat = db.query(Category).filter(Category.id == article_cat.category_id).first()
            category_obj = {"icon": cat.icon, "name": cat.name} if cat else None
        
        result.append({
            "id": article.id,
            "title": article.title,
            "slug": article.slug,
            "description": article.description,
            "views": article.views,
            "likes": article.likes,
            "created_at": article.created_at.isoformat(),
            "user_id": article.user_id,
            "author_name": author.username if author else f"Автор #{article.user_id}",
            "author_avatar": author.avatar if author else 'default.png',
            "type": "article",
            "category": category_obj
        })
    
    return {"articles": result, "total": total_count, "has_more": offset + limit < total_count}

# ============ ЗАГРУЗКА ИЗОБРАЖЕНИЙ ============
@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...), request: Request = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return {"error": "Не авторизован"}
    
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if file.content_type not in allowed_types:
        return {"error": "Можно загружать только JPEG, PNG, GIF или WEBP"}
    
    os.makedirs("static/uploads", exist_ok=True)
    ext = Path(file.filename).suffix.lower()
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = f"static/uploads/{filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    return {"location": f"/static/uploads/{filename}"}

@app.post("/profile/edit-avatar")
async def edit_avatar_ajax(request: Request, avatar: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return {"error": "Не авторизован"}
    
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if avatar.content_type not in allowed_types:
        return {"error": "Можно загружать только JPEG, PNG, GIF или WEBP"}
    
    os.makedirs("static/avatars", exist_ok=True)
    
    if user.avatar and user.avatar != 'default.png':
        old_path = f"static/avatars/{user.avatar}"
        if os.path.exists(old_path):
            os.remove(old_path)
    
    file_extension = Path(avatar.filename).suffix.lower()
    filename = f"{uuid.uuid4().hex}{file_extension}"
    file_path = f"static/avatars/{filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(avatar.file, buffer)
    
    user.avatar = filename
    db.commit()
    
    return {"success": True, "avatar": filename}

@app.get("/admin/slider/delete/{item_id}")
async def delete_slider_item_get(item_id: int, request: Request, db: Session = Depends(get_db)):
    print(f"\n=== GET УДАЛЕНИЕ СЛАЙДА {item_id} ===")
    
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        print("❌ Нет прав админа")
        return RedirectResponse(url="/", status_code=303)
    
    item = db.query(SliderItem).filter(SliderItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
        print(f"🗑️ Слайд {item_id} УДАЛЁН!")
    else:
        print(f"❌ Слайд {item_id} НЕ НАЙДЕН!")
    
    return RedirectResponse(url="/admin/slider", status_code=303)

    # ============ ВИДЕО ============

@app.get("/videos", response_class=HTMLResponse)
async def videos_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    videos = db.query(Video).filter(Video.is_published == True).order_by(Video.created_at.desc()).all()
    
    # Добавляем имена авторов
    for video in videos:
        author = db.query(User).filter(User.id == video.user_id).first()
        video.author_name = author.username if author else f"Автор #{video.user_id}"
        video.author_avatar = author.avatar if author else 'default.png'
    
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("videos.html", {
        "request": request,
        "user": user,
        "videos": videos,
        "slider_items": slider_items,
        "meta_title": "Видео - StoryBlog",
        "meta_description": "Видео от авторов StoryBlog"
    })

# ============ ЛАЙКИ ВИДЕО ============
@app.post("/video-like/{video_id}")
async def like_video(video_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    existing_like = db.query(VideoLike).filter(
        VideoLike.video_id == video_id, 
        VideoLike.user_id == user.id
    ).first()
    
    video = db.query(Video).filter(Video.id == video_id).first()
    
    if existing_like:
        db.delete(existing_like)
        video.likes -= 1
    else:
        new_like = VideoLike(video_id=video_id, user_id=user.id)
        db.add(new_like)
        video.likes += 1
        
        # ========== ДОБАВИТЬ УВЕДОМЛЕНИЕ ==========
        if video.user_id != user.id:
            create_notification(
                db=db,
                user_id=video.user_id,
                from_user_id=user.id,
                article_id=None,
                type="video_like",
                message=f"{user.username} лайкнул ваше видео «{video.title[:30]}»",
                link=f"/video/{video_id}"
            )
        # =========================================
    
    db.commit()
    return RedirectResponse(url=f"/video/{video_id}", status_code=303)

# ============ КОММЕНТАРИИ ВИДЕО ============
@app.post("/video-comment/{video_id}")
async def add_video_comment(
    video_id: int,
    request: Request,
    text: str = Form(...),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return RedirectResponse(url="/videos", status_code=303)
    
    new_comment = VideoComment(video_id=video_id, user_id=user.id, text=text)
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)
    
    # ========== ДОБАВИТЬ УВЕДОМЛЕНИЕ ==========
    if video.user_id != user.id:
        create_notification(
            db=db,
            user_id=video.user_id,
            from_user_id=user.id,
            article_id=None,
            type="video_comment",
            message=f"{user.username} оставил комментарий к вашему видео «{video.title[:30]}»",
            link=f"/video/{video_id}#comment-{new_comment.id}"
        )
    
    # Уведомления для @упоминаний
    import re
    mention_pattern = r'@([a-zA-Z0-9_а-яА-Я]+)'
    mentions = re.findall(mention_pattern, text)
    
    for username in mentions:
        mentioned_user = db.query(User).filter(User.username == username).first()
        if mentioned_user and mentioned_user.id != user.id and mentioned_user.id != video.user_id:
            create_notification(
                db=db,
                user_id=mentioned_user.id,
                from_user_id=user.id,
                article_id=None,
                type="mention",
                message=f"{user.username} упомянул вас в комментарии к видео «{video.title[:30]}»",
                link=f"/video/{video_id}#comment-{new_comment.id}"
            )
    # =========================================
    
    return RedirectResponse(url=f"/video/{video_id}#comment-{new_comment.id}", status_code=303)


# ============ УДАЛЕНИЕ КОММЕНТАРИЯ ВИДЕО ============
@app.post("/video-comment/delete/{comment_id}")
async def delete_video_comment(comment_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return {"success": False, "error": "Не авторизован"}
    
    comment = db.query(VideoComment).filter(VideoComment.id == comment_id).first()
    if not comment:
        return {"success": False, "error": "Комментарий не найден"}
    
    # Проверяем, что пользователь - автор комментария или админ
    if comment.user_id != user.id and not user.is_admin:
        return {"success": False, "error": "Вы можете удалять только свои комментарии"}
    
    db.delete(comment)
    db.commit()
    
    return {"success": True}

@app.get("/video/{video_id}", response_class=HTMLResponse)
async def video_detail(request: Request, video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    user = get_current_user(request, db)
    
    if not video or (not video.is_published and (not user or user.id != video.user_id)):
        return templates.TemplateResponse("404.html", {"request": request, "user": user}, status_code=404)
    
    # Увеличиваем счётчик просмотров
    video.views += 1
    db.commit()
    
    author = db.query(User).filter(User.id == video.user_id).first()
    video.author_name = author.username if author else f"Автор #{video.user_id}"
    video.author_avatar = author.avatar if author else 'default.png'
    
    comments = db.query(VideoComment).filter(VideoComment.video_id == video_id).order_by(VideoComment.created_at.desc()).all()
    for comment in comments:
        comment_author = db.query(User).filter(User.id == comment.user_id).first()
        comment.author_name = comment_author.username if comment_author else f"Пользователь #{comment.user_id}"
        comment.id = comment.id
    
    user_liked = False
    if user:
        user_liked = db.query(VideoLike).filter(VideoLike.video_id == video_id, VideoLike.user_id == user.id).first() is not None
    
    is_subscribed = False
    if user and user.id != video.user_id:
        is_subscribed = db.query(Subscription).filter(
            Subscription.subscriber_id == user.id,
            Subscription.author_id == video.user_id
        ).first() is not None
    
    # Проверка, в закладках ли видео
    is_bookmarked = False
    if user:
        is_bookmarked = db.query(VideoBookmark).filter(
            VideoBookmark.user_id == user.id,
            VideoBookmark.video_id == video_id
        ).first() is not None
    
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("video_detail.html", {
        "request": request,
        "video": video,
        "comments": comments,
        "user": user,
        "user_liked": user_liked,
        "is_subscribed": is_subscribed,
        "is_bookmarked": is_bookmarked,
        "slider_items": slider_items,
        "meta_title": video.title,
        "meta_description": video.description[:150] if video.description else ""
    })

@app.get("/create-video", response_class=HTMLResponse)
async def create_video_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
    
    return templates.TemplateResponse("create_video.html", {
        "request": request,
        "user": user,
        "slider_items": slider_items
    })

@app.post("/create-video")
async def create_video(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    is_published: bool = Form(True),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    form = await request.form()
    video_file = form.get("video_file")
    thumbnail_file = form.get("thumbnail")  # ← ДОБАВИТЬ
    
    video_url = ""
    thumbnail_url = ""
    
    # Загружаем видео
    if video_file and video_file.filename:
        allowed_types = ["video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"]
        if video_file.content_type not in allowed_types:
            slider_items = db.query(SliderItem).filter(SliderItem.is_active == True).order_by(SliderItem.order).all()
            return templates.TemplateResponse("create.html", {
                "request": request,
                "user": user,
                "error": "Можно загружать только MP4, WebM, MOV или AVI",
                "categories": db.query(Category).all(),
                "slider_items": slider_items
            })
        
        os.makedirs("static/uploads/videos", exist_ok=True)
        ext = Path(video_file.filename).suffix.lower()
        filename = f"video_{uuid.uuid4().hex}{ext}"
        file_path = f"static/uploads/videos/{filename}"
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(video_file.file, buffer)
        
        video_url = f"/static/uploads/videos/{filename}"
    
    # Загружаем превью
    if thumbnail_file and thumbnail_file.filename:
        allowed_image_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
        if thumbnail_file.content_type in allowed_image_types:
            os.makedirs("static/uploads/videos/thumbnails", exist_ok=True)
            ext = Path(thumbnail_file.filename).suffix.lower()
            thumb_filename = f"thumb_{uuid.uuid4().hex}{ext}"
            thumb_path = f"static/uploads/videos/thumbnails/{thumb_filename}"
            
            with open(thumb_path, "wb") as buffer:
                shutil.copyfileobj(thumbnail_file.file, buffer)
            
            thumbnail_url = f"/static/uploads/videos/thumbnails/{thumb_filename}"
    
    # Если превью не загружено, используем дефолтное
    if not thumbnail_url:
        thumbnail_url = "/static/uploads/videos/default_thumb.jpg"
    
    new_video = Video(
        title=title,
        description=description,
        video_url=video_url,
        thumbnail_url=thumbnail_url,
        user_id=user.id,
        is_published=is_published
    )
    db.add(new_video)
    db.commit()
    
    return RedirectResponse(url="/videos", status_code=303)

@app.post("/delete-video/{video_id}")
async def delete_video(video_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.user_id != user.id:
        return RedirectResponse(url="/profile", status_code=303)
    
    # Удаляем комментарии и лайки к видео
    db.query(VideoComment).filter(VideoComment.video_id == video_id).delete()
    db.query(VideoLike).filter(VideoLike.video_id == video_id).delete()
    db.query(VideoBookmark).filter(VideoBookmark.video_id == video_id).delete()
    
    # Удаляем файл видео с диска (с обработкой ошибки)
    if video.video_url:
        file_path = video.video_url.replace("/static/", "static/")
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"✅ Файл удалён: {file_path}")
        except PermissionError:
            print(f"⚠️ Файл занят, пропускаем удаление: {file_path}")
            # Файл занят, но продолжаем - удаляем запись из БД
    
    # Удаляем превью если есть
    if video.thumbnail_url and video.thumbnail_url != "/static/uploads/videos/default_thumb.jpg":
        thumb_path = video.thumbnail_url.replace("/static/", "static/")
        try:
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
        except PermissionError:
            pass
    
    # Удаляем запись из БД
    db.delete(video)
    db.commit()
    
    return RedirectResponse(url="/profile", status_code=303)

    # ============ ЗАКЛАДКИ ВИДЕО ============
@app.post("/video-bookmark/{video_id}")
async def toggle_video_bookmark(video_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    existing = db.query(VideoBookmark).filter(
        VideoBookmark.user_id == user.id,
        VideoBookmark.video_id == video_id
    ).first()
    
    if existing:
        db.delete(existing)
        db.commit()
    else:
        new_bookmark = VideoBookmark(user_id=user.id, video_id=video_id)
        db.add(new_bookmark)
        db.commit()
    
    return RedirectResponse(url=f"/video/{video_id}", status_code=303)

    # ============ ЖАЛОБЫ ============
@app.post("/complaint/{content_type}/{content_id}")
async def add_complaint(
    content_type: str,
    content_id: int,
    request: Request,
    reason: str = Form(...),
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Проверяем, существует ли контент
    if content_type == "article":
        content = db.query(Article).filter(Article.id == content_id).first()
        if not content:
            return RedirectResponse(url="/", status_code=303)
    elif content_type == "video":
        content = db.query(Video).filter(Video.id == content_id).first()
        if not content:
            return RedirectResponse(url="/videos", status_code=303)
    else:
        return RedirectResponse(url="/", status_code=303)
    
    # Создаём жалобу
    new_complaint = Complaint(
        user_id=user.id,
        content_type=content_type,
        content_id=content_id,
        reason=reason
    )
    db.add(new_complaint)
    db.commit()
    
    # Перенаправляем с сообщением об успехе
    if content_type == "article":
        article = db.query(Article).filter(Article.id == content_id).first()
        return RedirectResponse(url=f"/article/{article.slug}?complaint=success", status_code=303)
    else:
        return RedirectResponse(url=f"/video/{content_id}?complaint=success", status_code=303)