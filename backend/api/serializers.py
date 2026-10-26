from rest_framework import serializers
from .models import DiningGroups, Members, Restaurants

DIETARY = {'vegetarian', 'vegan', 'gluten_free', 'dairy_free', 'nut_free', 'halal', 'kosher'}


class RestaurantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Restaurants
        fields = [
            'id', 'name', 'neighborhood', 'cuisines', 'rating',
            'median_entree_price', 'min_entree_price', 'max_entree_price',
            'dietary_tags', 'menu_style',
        ]


class MemberSerializer(serializers.ModelSerializer):
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


class GroupSerializer(serializers.ModelSerializer):
    members = MemberSerializer(many=True, read_only=True)
    host_member_id = serializers.IntegerField(read_only=True)
    started = serializers.SerializerMethodField()

    class Meta:
        model = DiningGroups
        fields = ['id', 'invite_code', 'name', 'host_member_id', 'started', 'members']

    def get_started(self, group):
        return group.started_at is not None