import secrets

from rest_framework.exceptions import PermissionDenied

from django.conf import settings
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Value, When
from django.shortcuts import get_object_or_404
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils import timezone

from .models import DiningGroups, MenuItems, Members, Restaurants, Swipes
from .serializers import (GroupSerializer, OwnMemberSerializer,
                          RestaurantSerializer)

CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'   # no 0/O/1/I so codes are easy to read aloud


# Diet labels are printed on individual dishes, so "at least one entree carries the label"
# is enough. Halal and kosher are about the restaurant itself, so those use the
# restaurant-level tags instead.
DISH_LEVEL_DIETS = {'vegetarian', 'vegan', 'gluten_free', 'dairy_free', 'nut_free'}


def available_restaurants():
    """Restaurants with a parsed menu. Fictional sample data is hidden unless
    INCLUDE_SAMPLE_RESTAURANTS = True is set in settings.py."""
    qs = Restaurants.objects.filter(menu_status='parsed')
    if not getattr(settings, 'INCLUDE_SAMPLE_RESTAURANTS', False):
        qs = qs.exclude(place_id__startswith='sample_')
    return qs


def fits_diet(qs, restrictions):
    for r in restrictions:
        if r in DISH_LEVEL_DIETS:
            qs = qs.filter(Exists(MenuItems.objects.filter(
                restaurant=OuterRef('pk'), category='entree', dietary_tags__contains=[r])))
        else:
            qs = qs.filter(dietary_tags__contains=[r])
    return qs


def new_invite_code():
    while True:
        code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if not DiningGroups.objects.filter(invite_code=code).exists():
            return code


class RestaurantList(ListAPIView):
    serializer_class = RestaurantSerializer

    def get_queryset(self):
        qs = available_restaurants().order_by('-rating')
        max_price = self.request.query_params.get('max_price')
        if max_price:
            qs = qs.filter(median_entree_price__lte=max_price)
        return qs


class GroupCreate(APIView):
    """POST /api/groups/  {"name": "Friday dinner"}  ->  the new group with its invite code"""

    def post(self, request):
        group = DiningGroups.objects.create(
            invite_code=new_invite_code(),
            name=request.data.get('name', ''),
        )
        return Response(GroupSerializer(group).data, status=201)


class GroupDetail(RetrieveAPIView):
    """GET /api/groups/ABC123/  ->  group info and its members"""
    queryset = DiningGroups.objects.all()
    serializer_class = GroupSerializer
    lookup_field = 'invite_code'


def member_from_token(request, member_id):
    """The member this request is really from. The token never leaves their own browser."""
    member = get_object_or_404(Members, pk=member_id)
    token = request.headers.get('X-Member-Token')
    if not token or not member.token or not secrets.compare_digest(token, member.token):
        raise PermissionDenied('Not your profile.')
    return member


def build_deck(group):
    """One shared deck: restaurants that fit EVERYONE's budget and diets, best fit for the
    group's cuisine interests first. Nobody can tell whose limit shaped it."""
    members = list(Members.objects.filter(group=group))
    lowest = min(m.max_entree_budget for m in members)
    qs = available_restaurants().filter(median_entree_price__lte=lowest)
    diets = {d for m in members for d in m.dietary_restrictions}
    qs = fits_diet(qs, diets)
    cuisine_votes = {}
    for m in members:
        for c in m.cuisine_prefs:
            cuisine_votes[c] = cuisine_votes.get(c, 0) + 1
    rows = sorted(qs, key=lambda r: (-sum(cuisine_votes.get(c, 0) for c in (r.cuisines or [])),
                                     -(r.rating or 0)))
    return [r.id for r in rows[:getattr(settings, 'DECK_SIZE', 20)]]


class GroupJoin(APIView):
    """POST /api/groups/ABC123/join/ -> the new member, including their private token"""

    def post(self, request, invite_code):
        group = get_object_or_404(DiningGroups, invite_code=invite_code.upper())
        if group.started_at is not None:
            return Response({'detail': 'Swiping has already started for this group.'}, status=400)
        serializer = OwnMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = serializer.save(group=group, token=secrets.token_urlsafe(24))
        if group.host_member_id is None:          # the first person to join is the host
            group.host_member = member
            group.save(update_fields=['host_member'])
        data = OwnMemberSerializer(member).data
        data['token'] = member.token
        return Response(data, status=201)


class MemberMe(APIView):
    """GET/PATCH /api/members/5/  (needs X-Member-Token) -> only YOUR own preferences"""

    def get(self, request, member_id):
        return Response(OwnMemberSerializer(member_from_token(request, member_id)).data)

    def patch(self, request, member_id):
        member = member_from_token(request, member_id)
        if member.group.started_at is not None:
            return Response({'detail': 'Swiping already started; preferences are locked.'}, status=400)
        s = OwnMemberSerializer(member, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


class GroupStart(APIView):
    """POST /api/groups/ABC123/start/ {"member_id": 5} + X-Member-Token -> host only; builds the shared deck"""

    def post(self, request, invite_code):
        group = get_object_or_404(DiningGroups, invite_code=invite_code.upper())
        host = member_from_token(request, request.data.get('member_id'))
        if host.id != group.host_member_id:
            return Response({'detail': 'Only the host can start swiping.'}, status=403)
        if group.started_at is None:
            deck = build_deck(group)
            if not deck:
                return Response({'detail': "No restaurants fit everyone in the group yet. "
                                           "Try raising a budget or loosening a restriction."}, status=400)
            group.deck_ids = deck
            group.started_at = timezone.now()
            group.save(update_fields=['deck_ids', 'started_at'])
        return Response(GroupSerializer(group).data)


class NextCards(APIView):
    """GET /api/members/5/next/ (X-Member-Token) -> the shared deck minus what you've swiped, plus progress"""

    def get(self, request, member_id):
        member = member_from_token(request, member_id)
        deck = member.group.deck_ids or []
        done_ids = set(Swipes.objects.filter(member=member).values_list('restaurant_id', flat=True))
        by_id = {r.id: r for r in Restaurants.objects.filter(id__in=deck)}
        remaining = [by_id[i] for i in deck if i in by_id and i not in done_ids]
        return Response({
            'done': len(deck) - len(remaining),
            'total': len(deck),
            'cards': RestaurantSerializer(remaining[:10], many=True).data,
        })


class SwipeCreate(APIView):
    """POST /api/swipes/ {"member_id", "restaurant_id", "liked"} + X-Member-Token"""

    def post(self, request):
        member = member_from_token(request, request.data.get('member_id'))
        if request.data.get('restaurant_id') not in (member.group.deck_ids or []):
            return Response({'detail': 'Not in this group\'s deck.'}, status=400)
        restaurant = get_object_or_404(Restaurants, pk=request.data.get('restaurant_id'))
        liked = request.data.get('liked')
        if not isinstance(liked, bool):
            return Response({'liked': 'must be true or false'}, status=400)
        Swipes.objects.update_or_create(member=member, restaurant=restaurant, defaults={'liked': liked})
        return Response({'ok': True}, status=201)


class GroupMatches(APIView):
    """GET /api/groups/ABC123/matches/ -> restaurants where EVERY member swiped yes"""

    def get(self, request, invite_code):
        group = get_object_or_404(DiningGroups, invite_code=invite_code.upper())
        member_count = Members.objects.filter(group=group).count()
        matched_ids = (Swipes.objects
                       .filter(member__group=group, liked=True)
                       .values('restaurant')
                       .annotate(yes=Count('id'))
                       .filter(yes=member_count)
                       .values_list('restaurant', flat=True))
        matches = Restaurants.objects.filter(id__in=matched_ids).order_by('-rating')
        return Response({
            'member_count': member_count,
            'matches': RestaurantSerializer(matches, many=True).data,
        })