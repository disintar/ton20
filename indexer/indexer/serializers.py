from rest_framework import serializers
from .models import Ton20Tick, Ton20Wallet, TransactionStatus, Ton20StateSerialized


class Ton20TickSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ton20Tick
        fields = '__all__'

class Ton20TickSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ton20Tick
        fields = '__all__'

class Ton20StateSerializedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ton20StateSerialized
        fields = ['state_boc']

class Ton20WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ton20Wallet
        fields = '__all__'


class TransactionStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionStatus
        fields = '__all__'
