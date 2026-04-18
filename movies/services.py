from groq import Groq
from users.models import Watchlist
from django.conf import settings


def get_ai(user, message='' ,media_type='all'):
        # This message is a user request
        
        type_instructions = {
            "movie": "Recommend only movies, animated films and anime movies — no series or episodes.",
            "tv":    "Recommend only series, doramas, anime series and animated series — no movies.",
            "all":   "Recommend any format — movies, series, anime, doramas, cartoons.",
        }.get(media_type, "Recommend any format — movies, series, anime, doramas, cartoons.")





        watchlist =  Watchlist.objects.filter(user=user).select_related('movie')
         
        if not watchlist.exists():
            return {"error": "Please add movie for your wathclist"}
        

        movie_list = []
        for item in watchlist[:20]:
            watchlist_status =  "viewed" if item.watched else "not viewed"
            movie_list.append(f"-{item.movie.title} - {watchlist_status}")
        
        movie_text = "\n".join(movie_list)


        if message:
            final_message = f"My Watchlist:\n{movie_text}\n\nMy query: {message}"
        else:
            final_message = f"My Watchlist:\n{movie_text}\n\nWhat would you recommend watching?"


        try:

            client = Groq(api_key=settings.GROQ_API_KEY)
            
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        'role': 'system',
                        'content': f"""You are a cinema expert assistant with deep knowledge of movies, series, anime, and doramas.

                        WHAT YOU DO:
                        - Answer questions about specific movies, series, anime, directors, actors
                        - Recommend 3-5 titles when user asks for recommendations, based on their watchlist: {type_instructions}
                        - If asked about anything unrelated to cinema — respond EXACTLY: "I only answer questions about movies and series."

                        RECOMMENDATION LOGIC:
                        - If watchlist exists, prioritize it
                        - If the user says something like "I liked Naruto", "something like Interstellar", "anime like Death Note",
                        use THAT as the main recommendation signal even if watchlist is empty
                        - Never require watchlist to make recommendations
                        - If user asks only a factual question, answer it without recommendations


                        FORMATTING RULES:
                        For recommendations use this exact format:

                        ► TITLE (YEAR)
                        ✦ Genre: Action / Thriller
                        ✦ Why you'll like it: [1-2 sentences connecting to user's watchlist]
                        ✦ Rating: IMDb X.X/10

                        [blank line between each recommendation]

                        For answers about a specific movie/anime use this format:

                        📌 TITLE (YEAR)
                        • Director: Name
                        • Genre: ...
                        • Plot: [2-3 sentences]
                        • Notable for: [what makes it special]

                        STRICT RULES:
                        - NEVER invent non-existent movies or fake information
                        - NEVER recommend if user just asks a question
                        - Keep answers concise — max 150 words per recommendation
                        - Always use the formatting above — never plain unstructured text
                        - Always respond in English"""
                    },
                    {
                        'role': 'user',
                        'content': final_message
                    }
                ],
                max_tokens=800,
                temperature=0.7
            )

            return {"answer": response.choices[0].message.content,
                             "based_on": watchlist.count()}

        except Exception:
            return {"error": "API is unavailable"},
                            
                            
    

