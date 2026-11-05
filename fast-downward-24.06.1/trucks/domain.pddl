; IPC5 Domain: Trucks Propositional
; Authors: Yannis Dimopoulos, Alfonso Gerevini and Alessandro Saetti
; Extended with road distance (miles), road speed (mph), and grid coordinates.

(define (domain Trucks)
(:requirements :typing :disjunctive-preconditions)

(:types truckarea time location locatable - object
        truck package - locatable
        mile mph gridcoord - object)

(:predicates (at ?x - locatable ?l - location)
             (in ?p - package ?t - truck ?a - truckarea)
             (connected ?x ?y - location)
             (free ?a - truckarea ?t - truck)
             (time-now ?t - time)
             (next ?t1 - time ?t2 - time)
             (le ?t1 - time ?t2 - time)
             (delivered ?p - package ?l - location ?t - time)
             (at-destination ?p - package ?l - location)
             (closer ?a1 - truckarea ?a2 - truckarea)
             (road-distance ?x ?y - location ?d - mile)
             (road-speed ?x ?y - location ?s - mph)
             (road-span ?x ?y - location ?t1 ?t2 - time)
             (zero-time-road ?x ?y - location)
             (loc-x ?l - location ?c - gridcoord)
             (loc-y ?l - location ?c - gridcoord))

(:action load
 :parameters (?p - package ?t - truck ?a1 - truckarea ?l - location)
 :precondition (and (at ?t ?l) (at ?p ?l) (free ?a1 ?t)
                    (forall (?a2 - truckarea)
                            (imply (closer ?a2 ?a1) (free ?a2 ?t))))
 :effect (and (not (at ?p ?l)) (not (free ?a1 ?t)) (in ?p ?t ?a1)))

(:action unload
 :parameters (?p - package ?t - truck ?a1 - truckarea ?l - location)
 :precondition (and (at ?t ?l) (in ?p ?t ?a1)
                    (forall (?a2 - truckarea)
                            (imply (closer ?a2 ?a1) (free ?a2 ?t))))
 :effect (and (not (in ?p ?t ?a1)) (free ?a1 ?t) (at ?p ?l)))

; drive advances the clock by the road's rounded travel time:
; duration = round_half_up(distance_miles / speed_mph), minimum 0.
; The (road-span ?from ?to ?t1 ?t2) fact encodes "departing at ?t1 on this
; road, you arrive at ?t2" and is precomputed in the problem file.
(:action drive
 :parameters (?t - truck ?from ?to - location ?t1 ?t2 - time)
 :precondition (and (at ?t ?from) (connected ?from ?to)
                    (time-now ?t1) (road-span ?from ?to ?t1 ?t2))
 :effect (and (not (at ?t ?from)) (not (time-now ?t1))
              (time-now ?t2) (at ?t ?to)))

; drive-instant handles roads whose rounded travel time is 0t:
; the trip completes within the current hour, so the clock does not move.
; It requires the (zero-time-road ?from ?to) fact, which is emitted only
; for 0t roads, keeping it fully disjoint from the multi-hour drive action.
(:action drive-instant
 :parameters (?t - truck ?from ?to - location ?t1 - time)
 :precondition (and (at ?t ?from) (connected ?from ?to)
                    (zero-time-road ?from ?to) (time-now ?t1))
 :effect (and (not (at ?t ?from)) (at ?t ?to)))

(:action deliver
 :parameters (?p - package ?l - location ?t1 ?t2 - time)
 :precondition (and (at ?p ?l) (time-now ?t1) (le ?t1 ?t2))
 :effect (and (not (at ?p ?l)) (delivered ?p ?l ?t2) (at-destination ?p ?l)))

)
