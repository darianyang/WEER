import logging

import numpy as np
import operator
from westpa.core.we_driver import WEDriver

from weer import WEER

log = logging.getLogger(__name__)

class WEERDriver(WEDriver):
    '''
    This introduces a weight resampling procedure before or after (TODO)
    the split/merge resampling.
    '''

    def _run_we(self):
        '''
        Run recycle/split/merge. Do not call this function directly; instead, use
        populate_initial(), rebin_current(), or construct_next().
        '''
        self._recycle_walkers()

        # sanity check
        self._check_pre()

        # Regardless of current particle count, always split overweight particles and merge underweight particles
        # Then and only then adjust for correct particle count
        total_number_of_subgroups = 0
        total_number_of_particles = 0
        for (ibin, bin) in enumerate(self.next_iter_binning):
            if len(bin) == 0:
                continue

            # Splits the bin into subgroups as defined by the called function
            target_count = self.bin_target_counts[ibin]
            subgroups = self.subgroup_function(self, ibin, **self.subgroup_function_kwargs)
            total_number_of_subgroups += len(subgroups)
            # grab segments and weights and pcoords
            segments = np.array(sorted(bin, key=operator.attrgetter('weight')), dtype=np.object_)
            weights = np.array(list(map(operator.attrgetter('weight'), segments)))
            pcoords = np.array(list(map(operator.attrgetter('pcoord'), segments)))

            # get all pcoords, not just the final frame
            curr_segments = np.array(sorted(self.current_iter_segments, 
                                            key=operator.attrgetter('weight')), dtype=np.object_)
            curr_pcoords = np.array(list(map(operator.attrgetter('pcoord'), curr_segments)))

            # TODO: update weights based on WEER
            reweight = WEER(curr_pcoords, weights, 'true_1d_odld.txt')
            # TODO: somehow set new weights to each segment
            weights = reweight.method()
            map(operator.attrgetter('weight'), segments) = weights

            # Calculate ideal weight and clear the bin
            ideal_weight = weights.sum() / target_count
            bin.clear()
            # Determines to see whether we have more sub bins than we have target walkers in a bin (or equal to), and then uses
            # different logic to deal with those cases.  Should devolve to the Huber/Kim algorithm in the case of few subgroups.
            if len(subgroups) >= target_count:
                for i in subgroups:
                    # Merges all members of set i.  Checks to see whether there are any to merge.
                    if len(i) > 1:
                        (segment, parent) = self._merge_walkers(
                            list(i),
                            np.add.accumulate(np.array(list(map(operator.attrgetter('weight'), i)))),
                            i,
                        )
                        i.clear()
                        i.add(segment)
                    # Add all members of the set i to the bin.  This keeps the bins in sync for the adjustment step.
                    bin.update(i)

                if len(subgroups) > target_count:
                    self._adjust_count(bin, subgroups, target_count)

            if len(subgroups) < target_count:
                for i in subgroups:
                    self._split_by_weight(i, target_count, ideal_weight)
                    self._merge_by_weight(i, target_count, ideal_weight)
                    # Same logic here.
                    bin.update(i)
                if self.do_adjust_counts:
                    # A modified adjustment routine is necessary to ensure we don't unnecessarily destroy trajectory pathways.
                    self._adjust_count(bin, subgroups, target_count)
            if self.do_thresholds:
                for i in subgroups:
                    self._split_by_threshold(bin, i)
                    self._merge_by_threshold(bin, i)
                for iseg in bin:
                    if iseg.weight > self.largest_allowed_weight or iseg.weight < self.smallest_allowed_weight:
                        log.warning(
                            f'Unable to fulfill threshold conditions for {iseg}. The given threshold range is likely too small.'
                        )
            total_number_of_particles += len(bin)
        log.debug('Total number of subgroups: {!r}'.format(total_number_of_subgroups))

        self._check_post()

        self.new_weights = self.new_weights or []

        log.debug('used initial states: {!r}'.format(self.used_initial_states))
        log.debug('available initial states: {!r}'.format(self.avail_initial_states))