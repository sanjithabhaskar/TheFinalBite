import secrets

from django.utils import timezone

from django.db.models import Case, Count, IntegerField, Value, When
from django.shortcuts import get_object_or_404
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DiningGroups, Members, Restaurants, Swipes
from .serializers import GroupSerializer, MemberSerializer, RestaurantSerializer

CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'   # no 0/O/1/I so codes are easy to read aloud


def new_invite_code():
    while True:
        code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if not DiningGroups.objects.filter(invite_code=code).exists():
            return code


class RestaurantList(ListAPIView):
    serializer_class = RestaurantSerializer

    def get_queryset(self):
        qs = Restaurants.objects.filter(menu_status='parsed').order_by('-rating')
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


class GroupJoin(APIView):
    """POST /api/groups/ABC123/join/  {"name", "max_entree_budget", "dietary_restrictions", "cuisine_prefs"}"""

    def post(self, request, invite_code):
        group = get_object_or_404(DiningGroups, invite_code=invite_code.upper())
        if group.started_at is not None:
            return Response({'detail': 'Swiping has already started for this group.'}, status=400)
        serializer = MemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = serializer.save(group=group)
        if group.host_member_id is None:          # the first person to join is the host
            group.host_member = member
            group.save(update_fields=['host_member'])
        return Response(MemberSerializer(member).data, status=201)


class GroupStart(APIView):
    """POST /api/groups/ABC123/start/  {"member_id": 5}  ->  only the host can do this"""

    def post(self, request, invite_code):
        group = get_object_or_404(DiningGroups, invite_code=invite_code.upper())
        if request.data.get('member_id') != group.host_member_id:
            return Response({'detail': 'Only the host can start swiping.'}, status=403)
        if group.started_at is None:
            group.started_at = timezone.now()
            group.save(update_fields=['started_at'])
        return Response(GroupSerializer(group).data)


class NextCards(APIView):
    """GET /api/members/5/next/  ->  up to 10 restaurants this member hasn't swiped on and can eat/afford"""

    def get(self, request, member_id):
        member = get_object_or_404(Members, pk=member_id)
        already_swiped = Swipes.objects.filter(member=member).values('restaurant_id')

        qs = (Restaurants.objects
              .filter(menu_status='parsed', median_entree_price__lte=member.max_entree_budget)
              .exclude(id__in=already_swiped))
        if member.dietary_restrictions:
            qs = qs.filter(dietary_tags__contains=member.dietary_restrictions)

        if member.cuisine_prefs:   # preferred cuisines first, then best rated
            qs = qs.annotate(pref=Case(
                When(cuisines__overlap=member.cuisine_prefs, then=Value(0)),
                default=Value(1), output_field=IntegerField(),
            )).order_by('pref', '-rating')
        else:
            qs = qs.order_by('-rating')

        return Response(RestaurantSerializer(qs[:10], many=True).data)


class SwipeCreate(APIView):
    """POST /api/swipes/  {"member_id": 5, "restaurant_id": 12, "liked": true}"""

    def post(self, request):
        member = get_object_or_404(Members, pk=request.data.get('member_id'))
        restaurant = get_object_or_404(Restaurants, pk=request.data.get('restaurant_id'))
        liked = request.data.get('liked')
        if not isinstance(liked, bool):
            return Response({'liked': 'must be true or false'}, status=400)
        Swipes.objects.update_or_create(member=member, restaurant=restaurant, defaults={'liked': liked})
        return Response({'ok': True}, status=201)


class GroupMatches(APIView):
    """GET /api/groups/ABC123/matches/  ->  restaurants where EVERY member swiped yes"""

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