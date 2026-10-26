from rest_framework import serializers
from .models import DiningGroups, Members, Restaurants

DIETARY = {'vegetarian', 'vegan', 'gluten_free', 'dairy_free', 'nut_free', 'halal', 'kosher'}


class RestaurantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Restaurants
        fields = [
            'id', 'name', 'neighborhood', 'address', 'cuisines', 'rating',
            'median_entree_price', 'min_entree_price', 'max_entree_price',
            'dietary_tags', 'menu_style', 'website', 'menu_url',
        ]


class OwnMemberSerializer(serializers.ModelSerializer):
    """Everything about ONE person. Only ever returned to that person."""
    class Meta:
        model = Members
        fields = ['id', 'name', 'max_entree_budget', 'dietary_restrictions', 'cuisine_prefs']
        extra_kwargs = {
            'dietary_restrictions': {'required': False},
            'cuisine_prefs': {'required': False},
        }

    def validate_dietary_restrictions(self, value):
        unknown = set(value) - DIETARY
        if unknown:
            raise serializers.ValidationError(f'Unknown restrictions: {sorted(unknown)}')
        return value

    def validate_max_entree_budget(self, value):
        if value <= 0:
            raise serializers.ValidationError('Budget must be more than 0.')
        return value


class PublicMemberSerializer(serializers.ModelSerializer):
    """What the rest of the group may see: a name and swipe progress. Nothing else."""
    swiped = serializers.SerializerMethodField()

    class Meta:
        model = Members
        fields = ['id', 'name', 'swiped']

    def get_swiped(self, member):
        return member.swipes_set.count() if hasattr(member, 'swipes_set') else member.swipes.count()


class GroupSerializer(serializers.ModelSerializer):
    members = PublicMemberSerializer(many=True, read_only=True)
    host_member_id = serializers.IntegerField(read_only=True)
    host_name = serializers.SerializerMethodField()
    started = serializers.SerializerMethodField()
    deck_size = serializers.SerializerMethodField()

    class Meta:
        model = DiningGroups
        fields = ['id', 'invite_code', 'name', 'host_member_id', 'host_name',
                  'started', 'deck_size', 'members']

    def get_started(self, group):
        return group.started_at is not None

    def get_host_name(self, group):
        return group.host_member.name if group.host_member_id else None

    def get_deck_size(self, group):
        return len(group.deck_ids or [])