import os
import meilisearch
from app import create_app
from models import Product

def index_all_products():
    app = create_app(os.environ.get('FLASK_ENV', 'development'))
    with app.app_context():
        client = meilisearch.Client(
            os.environ.get('MEILI_HOST', 'http://127.0.0.1:7700'),
            os.environ.get('MEILI_MASTER_KEY', 'masterKey123')
        )
        
        index = client.index('products')
        index.update_settings({
            'searchableAttributes': ['name', 'description', 'category_name', 'tags'],
            'filterableAttributes': ['category_id', 'is_active', 'price'],
            'sortableAttributes': ['price', 'created_at']
        })
        
        products = Product.query.all()
        documents = []
        for p in products:
            documents.append({
                'id': p.id,
                'name': p.name,
                'description': p.description,
                'price': float(p.base_price),
                'category_id': p.category_id,
                'category_name': p.category.name if p.category else '',
                'is_active': p.is_active,
                'tags': p.occasion_tags,
                'created_at': p.created_at.timestamp() if p.created_at else 0
            })
        
        if documents:
            index.add_documents(documents)
            print(f'Successfully indexed {len(documents)} products into Meilisearch.')
        else:
            print('No products found to index.')

if __name__ == '__main__':
    index_all_products()
