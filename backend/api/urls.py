from django.urls import path
from .views import (GroupCreate, GroupDetail, GroupJoin, GroupMatches, GroupStart,
                    NextCards, RestaurantList, SwipeCreate)

urlpatterns = [
    path('restaurants/', RestaurantList.as_view()),
    path('groups/', GroupCreate.as_view()),
    path('groups/<str:invite_code>/', GroupDetail.as_view()),
    path('groups/<str:invite_code>/join/', GroupJoin.as_view()),
    path('groups/<str:invite_code>/start/', GroupStart.as_view()),
    path('groups/<str:invite_code>/matches/', GroupMatches.as_view()),
    path('members/<int:member_id>/next/', NextCards.as_view()),
    path('swipes/', SwipeCreate.as_view()),
]