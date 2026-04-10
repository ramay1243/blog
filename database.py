from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timedelta


Base = declarative_base()
engine = create_engine('sqlite:///blog.db', connect_args={'check_same_thread': False})

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    avatar = Column(String, default='default.png')
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

class Article(Base):
    __tablename__ = 'articles'
    id = Column(Integer, primary_key=True)
    title = Column(String, index=True)
    slug = Column(String, unique=True, index=True)
    description = Column(String, default='')
    content = Column(Text)
    user_id = Column(Integer, ForeignKey('users.id'))
    is_published = Column(Boolean, default=False)
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class Comment(Base):
    __tablename__ = 'comments'
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey('articles.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    text = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

class Like(Base):
    __tablename__ = 'likes'
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey('articles.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.now)

class SliderItem(Base):
    __tablename__ = 'slider_items'
    id = Column(Integer, primary_key=True)
    title = Column(String, default='')
    label = Column(String, default='')
    icon = Column(String, default='📖')
    image_url = Column(String, default='')
    link = Column(String, default='')
    is_active = Column(Boolean, default=True)
    order = Column(Integer, default=0)
    image_position = Column(String, default='cover')
    text_position = Column(String, default='center')
    text_color = Column(String, default='#ffffff')
    text_size = Column(String, default='medium')
    overlay_opacity = Column(Integer, default=30)
    created_at = Column(DateTime, default=datetime.now)

class PasswordReset(Base):
    __tablename__ = 'password_resets'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    code = Column(String, unique=True)
    expires_at = Column(DateTime, default=lambda: datetime.now() + timedelta(hours=1))
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

class Category(Base):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    slug = Column(String, unique=True)
    icon = Column(String, default='📁')
    color = Column(String, default='#ff8c00')
    created_at = Column(DateTime, default=datetime.now)

class ArticleCategory(Base):
    __tablename__ = 'article_categories'
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey('articles.id'))
    category_id = Column(Integer, ForeignKey('categories.id'))

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    from_user_id = Column(Integer, ForeignKey('users.id'))
    article_id = Column(Integer, ForeignKey('articles.id'), nullable=True)
    type = Column(String, default='comment')
    message = Column(String)
    is_read = Column(Boolean, default=False)
    link = Column(String, default='')
    created_at = Column(DateTime, default=datetime.now)

class Subscription(Base):
    __tablename__ = 'subscriptions'
    id = Column(Integer, primary_key=True)
    subscriber_id = Column(Integer, ForeignKey('users.id'))
    author_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.now)

class Bookmark(Base):
    __tablename__ = 'bookmarks'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    article_id = Column(Integer, ForeignKey('articles.id'))
    created_at = Column(DateTime, default=datetime.now)

class Video(Base):
    __tablename__ = 'videos'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, default='')
    video_url = Column(String, default='')
    thumbnail_url = Column(String, default='')
    user_id = Column(Integer, ForeignKey('users.id'))
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    is_published = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class VideoLike(Base):
    __tablename__ = 'video_likes'
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey('videos.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.now)

class VideoComment(Base):
    __tablename__ = 'video_comments'
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey('videos.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

class VideoBookmark(Base):
    __tablename__ = "video_bookmarks"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    video_id = Column(Integer, ForeignKey("videos.id"))
    created_at = Column(DateTime, default=datetime.now)

class Complaint(Base):
    __tablename__ = "complaints"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))  # Кто пожаловался
    content_type = Column(String, default="article")   # "article" или "video"
    content_id = Column(Integer)                       # ID статьи или видео
    reason = Column(Text)                              # Причина жалобы
    status = Column(String, default="pending")         # pending, reviewed, resolved, dismissed
    created_at = Column(DateTime, default=datetime.now)
    
    # Связи
    user = relationship("User")    

Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)