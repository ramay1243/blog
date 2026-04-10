from database import SessionLocal, Category

def init_categories():
    db = SessionLocal()
    
    # Список категорий: (название, slug, иконка)
    categories_data = [
        ('Личное', 'lichnoe', '💭'),
        ('Путешествия', 'puteshestviya', '✈️'),
        ('Технологии', 'tehnologii', '💻'),
        ('Юмор', 'yumor', '😂'),
        ('Истории', 'istorii', '📖'),
        ('Советы', 'sovety', '💡'),
    ]
    
    added = 0
    for name, slug, icon in categories_data:
        # Проверяем, есть ли уже такая категория
        existing = db.query(Category).filter(Category.slug == slug).first()
        if not existing:
            cat = Category(name=name, slug=slug, icon=icon)
            db.add(cat)
            added += 1
            print(f"✅ Добавлена категория: {icon} {name}")
        else:
            print(f"⏩ Категория уже существует: {icon} {name}")
    
    db.commit()
    db.close()
    
    print(f"\n📊 Итог: добавлено {added} новых категорий")

if __name__ == "__main__":
    init_categories()