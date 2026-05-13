import os
import sys
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from app import create_app
from models import OrderItem, Product, cache

def train_recommendation_model():
    print("Initializing Flask context...")
    app = create_app(os.environ.get('FLASK_ENV', 'development'))
    with app.app_context():
        print("Fetching OrderItems...")
        items = OrderItem.query.all()
        if not items:
            print("Not enough data to train model.")
            return

        # Prepare DataFrame: Order ID -> Product ID
        data = [{'order_id': item.order_id, 'product_id': item.product_id} for item in items]
        df = pd.DataFrame(data)

        # Create a user-item matrix where rows are orders and columns are products
        # A value of 1 means the product was in the order
        matrix = pd.crosstab(df['order_id'], df['product_id'])
        
        # Calculate item-item similarity using Cosine Similarity
        # This transposed matrix calculates similarity between products based on orders
        print("Calculating similarity matrix...")
        item_similarity = cosine_similarity(matrix.T)
        
        # Build dictionary mapping Product ID to a list of similar Product IDs
        product_ids = matrix.columns.tolist()
        recommendations = {}
        
        for idx, p_id in enumerate(product_ids):
            # Get similarity scores for this product
            sim_scores = list(enumerate(item_similarity[idx]))
            
            # Sort by highest similarity, excluding the item itself
            sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)
            
            # Get top 4 similar items (index 1 to 5 because 0 is the item itself)
            top_similar_indices = [i[0] for i in sim_scores[1:5]]
            top_similar_product_ids = [product_ids[i] for i in top_similar_indices]
            
            recommendations[p_id] = top_similar_product_ids
            
            # Cache the recommendations in Redis
            cache.set(f'recommendations_{p_id}', top_similar_product_ids, timeout=86400) # 24 hours

        print(f"Successfully trained and cached recommendations for {len(product_ids)} products.")

if __name__ == '__main__':
    train_recommendation_model()
